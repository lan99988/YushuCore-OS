"""Shared operation receipts and privacy-minimized workflow checkpoints."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from collections.abc import Mapping
from typing import Any

from .contracts import Request
from .metadata import safe_resource_refs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,99}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_INPUT_FIELDS = frozenset({
    "schema_version", "plugin_id", "plugin_version", "provider_digest", "project_ref", "request_id",
    "state_ledger_path", "data_path", "emitted_events", "run_id", "root_event_id", "causation_id",
    "depth", "mode", "host_mode", "resources",
})
_CONTEXT_METADATA_FIELDS = (
    "schema_version", "plugin_id", "plugin_version", "provider_digest", "project_ref", "request_id",
    "emitted_events", "run_id", "root_event_id", "causation_id", "depth",
)


def _error_code(result: Any) -> str:
    error = getattr(result, "error", None)
    if isinstance(error, Mapping):
        for key in ("error_code", "code", "reason"):
            value = error.get(key)
            if isinstance(value, str) and _CODE.fullmatch(value):
                return value
    value = getattr(result, "error_code", "")
    return value if isinstance(value, str) and _CODE.fullmatch(value) else ""


def _minimal_receipt(result: Any) -> dict[str, Any]:
    status = getattr(result, "status", None)
    request_id = getattr(result, "request_id", None)
    if not isinstance(status, str) or not isinstance(request_id, str):
        raise ValueError("结果收据缺少稳定状态或 request_id")
    receipt: dict[str, Any] = {"status": status, "request_id": request_id}
    code = _error_code(result)
    if code:
        # Result accepts `error`; storing only its stable code preserves that
        # public constructor while dropping messages, resources, and data.
        receipt["error"] = {"code": code}
    return receipt


def _context_dict(context: Any) -> dict[str, Any]:
    if hasattr(context, "to_dict"):
        context = context.to_dict()
    if not isinstance(context, Mapping):
        raise ValueError("插件上下文必须是对象")
    return dict(context)


def _context_metadata(context: Any) -> dict[str, Any]:
    source = _context_dict(context)
    if set(source) - _CONTEXT_INPUT_FIELDS:
        raise ValueError("插件上下文包含未知字段")
    if source.get("schema_version", 1) != 1:
        raise ValueError("插件上下文 schema_version 无效")
    for key in ("plugin_id", "plugin_version", "request_id"):
        value = source.get(key)
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"context {key} 格式无效")
    digest = source.get("provider_digest")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("context provider_digest 格式无效")
    project_ref = source.get("project_ref", "")
    if not isinstance(project_ref, str) or len(project_ref) > 200:
        raise ValueError("context project_ref 格式无效")
    emitted = source.get("emitted_events", [])
    if not isinstance(emitted, (list, tuple)) or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in emitted):
        raise ValueError("context emitted_events 格式无效")
    if len(emitted) != len(set(emitted)):
        raise ValueError("context emitted_events 必须唯一")
    for key in ("run_id", "root_event_id", "causation_id"):
        value = source.get(key, "")
        if not isinstance(value, str) or (value and not _ID.fullmatch(value)):
            raise ValueError(f"context {key} 格式无效")
    depth = source.get("depth", 0)
    if type(depth) is not int or depth < 0:
        raise ValueError("context depth 格式无效")
    return {
        "schema_version": 1,
        "plugin_id": source["plugin_id"],
        "plugin_version": source["plugin_version"],
        "provider_digest": digest,
        "project_ref": project_ref,
        "request_id": source["request_id"],
        "emitted_events": list(emitted),
        "run_id": source.get("run_id", ""),
        "root_event_id": source.get("root_event_id", ""),
        "causation_id": source.get("causation_id", ""),
        "depth": depth,
    }


def _event_id(request_id: str, index: int, event_type: str) -> str:
    seed = json.dumps({"request_id": request_id, "index": index, "type": event_type},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(seed.encode("utf-8")).hexdigest()


class StateStore:
    """Use the existing operations ledger; add workflow metadata without replacing it."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().absolute()

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("台账版本比当前执行器新，禁止写入")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    resource_key TEXT NOT NULL, status TEXT NOT NULL,
                    receipt TEXT, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS locks (
                    resource_key TEXT PRIMARY KEY, request_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    calendar_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    task_guid TEXT, snapshot TEXT NOT NULL,
                    PRIMARY KEY(calendar_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    plan_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    project_ref TEXT NOT NULL, status TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    plan_id TEXT NOT NULL, step_id TEXT NOT NULL,
                    capability TEXT NOT NULL, request_id TEXT NOT NULL,
                    depends_on TEXT NOT NULL, provider TEXT NOT NULL,
                    provider_version TEXT NOT NULL, status TEXT NOT NULL,
                    result_refs TEXT, error_code TEXT, updated TEXT NOT NULL,
                    PRIMARY KEY(plan_id, step_id),
                    FOREIGN KEY(plan_id) REFERENCES workflow_runs(plan_id)
                );
                CREATE TABLE IF NOT EXISTS event_outbox (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    envelope TEXT NOT NULL,
                    imported INTEGER NOT NULL DEFAULT 0 CHECK(imported IN (0,1)),
                    created TEXT NOT NULL,
                    imported_at TEXT
                );
                CREATE TABLE IF NOT EXISTS operation_contexts (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_outbox_pending
                    ON event_outbox(imported,created,event_id);
                CREATE TABLE IF NOT EXISTS receipt_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS receipt_resolutions_latest
                    ON receipt_resolutions(request_id,id);
            """)
            # Keep user_version=1 for compatibility with V0.1 executors.
            if version == 0:
                db.execute("PRAGMA user_version=1")
            db.commit()
        finally:
            db.close()

    @contextmanager
    def connect(self, *, write: bool = False):
        if write:
            self._prepare()
            db = sqlite3.connect(self.path, timeout=5)
        else:
            if not self.path.exists():
                yield None
                return
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", timeout=5, uri=True)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def receipt(self, request_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            if db is None:
                return None
            row = db.execute("SELECT * FROM operations WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["receipt"] = json.loads(value["receipt"]) if value["receipt"] else None
        return value

    def claim(self, request: Request) -> bool:
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT fingerprint FROM operations WHERE request_id=?", (request.request_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != request.fingerprint():
                    raise ValueError("同一请求 ID 被用于不同内容")
                return False
            try:
                db.execute("INSERT INTO locks VALUES (?,?)", (request.resource_key(), request.request_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("资源正在执行或等待结果核对") from exc
            db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?)", (
                request.request_id, request.fingerprint(), request.resource_key(), "dispatched", None, _now(),
            ))
        return True

    def _bind_context(self, request: Request | dict[str, Any], context: Any) -> bool:
        """Bind provider identity and event declarations before a v3 dispatch.

        The full request body remains outside this metadata table; only its
        stable fingerprint is stored alongside a strict projection of context.
        This private Core entry point lets later outbox writes verify their
        source identity instead of trusting plugin-supplied context fields.
        """
        if isinstance(request, Request):
            normalized_request = request
        elif isinstance(request, Mapping):
            try:
                normalized_request = Request(
                    request_id=request["request_id"],
                    capability=request["capability"],
                    intent=request["intent"],
                    fields=request.get("fields", {}),
                    target=request.get("target", {}),
                    project_ref=request.get("project_ref", ""),
                )
            except (KeyError, TypeError):
                raise ValueError("request 格式无效") from None
        else:
            raise ValueError("request 必须是 SDK Request 或请求对象")
        metadata = _context_metadata(context)
        if metadata["request_id"] != normalized_request.request_id:
            raise ValueError("context request_id 与 request 不匹配")
        if metadata["project_ref"] != normalized_request.project_ref:
            raise ValueError("context project_ref 与 request 不匹配")
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = normalized_request.fingerprint()
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT fingerprint,context_json FROM operation_contexts WHERE request_id=?",
                (normalized_request.request_id,),
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint or old["context_json"] != encoded:
                    raise ValueError("同一请求 ID 的执行上下文身份冲突")
                return False
            db.execute(
                "INSERT INTO operation_contexts(request_id,fingerprint,context_json,created) VALUES (?,?,?,?)",
                (normalized_request.request_id, fingerprint, encoded, _now()),
            )
        return True

    def record(self, result: Any) -> None:
        receipt = _minimal_receipt(result)
        with self.connect(write=True) as db:
            db.execute("UPDATE operations SET status=?,receipt=?,updated=? WHERE request_id=?", (
                result.status, json.dumps(receipt, ensure_ascii=False), _now(), result.request_id,
            ))
            if result.status not in {"unknown", "verification_pending", "partial", "abandoned"}:
                db.execute("DELETE FROM locks WHERE request_id=?", (result.request_id,))

    def record_with_events(self, result: Any, context: Any, emissions: list[dict[str, Any]]) -> None:
        """Write a minimal receipt and its allow-listed event envelopes atomically."""
        receipt = _minimal_receipt(result)
        request_id = result.request_id
        if not _ID.fullmatch(request_id):
            raise ValueError("request_id 格式无效")
        supplied_source = _context_metadata(context)
        if supplied_source["request_id"] != request_id:
            raise ValueError("context request_id 与结果不匹配")
        if not isinstance(emissions, (list, tuple)):
            raise ValueError("emissions 必须是数组")

        now = _now()
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            operation = db.execute(
                "SELECT fingerprint,status,receipt FROM operations WHERE request_id=?", (request_id,)
            ).fetchone()
            if operation is None:
                raise ValueError("操作台账中不存在 claim 记录")
            binding = db.execute(
                "SELECT fingerprint,context_json FROM operation_contexts WHERE request_id=?", (request_id,)
            ).fetchone()
            if binding is None:
                raise ValueError("request 尚未绑定 Core 执行上下文")
            if binding["fingerprint"] != operation["fingerprint"]:
                raise ValueError("request 与 Core 绑定身份不一致")
            bound_source = json.loads(binding["context_json"])
            if bound_source != supplied_source:
                raise ValueError("Core 绑定身份与提供的 context 不一致")

            events: list[dict[str, Any]] = []
            # Only confirmed success can publish successful business events. An
            # unknown or partial result keeps its uncertainty in the ledger.
            if result.status == "succeeded":
                allowed = set(bound_source["emitted_events"])
                for index, emission in enumerate(emissions):
                    if not isinstance(emission, Mapping):
                        raise ValueError("event emission 必须是对象")
                    if set(emission) - {"type", "resource_refs"}:
                        raise ValueError("event emission 只能包含 type 和 resource_refs")
                    event_type = emission.get("type")
                    if not isinstance(event_type, str) or not _ID.fullmatch(event_type):
                        raise ValueError("event type 格式无效")
                    if event_type not in allowed:
                        raise ValueError("event type 未授权")
                    event_identifier = _event_id(request_id, index, event_type)
                    causation_id = bound_source["causation_id"]
                    context_root = bound_source["root_event_id"]
                    depth = bound_source["depth"]
                    events.append({
                        "id": event_identifier,
                        "type": event_type,
                        "source_plugin": bound_source["plugin_id"],
                        "source_version": bound_source["plugin_version"],
                        "provider_digest": bound_source["provider_digest"],
                        "project_ref": bound_source["project_ref"],
                        "request_id": request_id,
                        "causation_id": causation_id,
                        "root_event_id": context_root or event_identifier,
                        "occurred_at": now,
                        "depth": depth + 1 if causation_id else 0,
                        "resource_refs": safe_resource_refs(emission.get("resource_refs", {})),
                    })

            encoded_receipt = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
            if operation["receipt"]:
                previous = json.loads(operation["receipt"])
                if previous != receipt:
                    raise ValueError("同一请求 ID 的收据内容冲突")
            else:
                db.execute("UPDATE operations SET status=?,receipt=?,updated=? WHERE request_id=?",
                           (result.status, encoded_receipt, now, request_id))
            for event in events:
                encoded_event = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                existing = db.execute("SELECT envelope FROM event_outbox WHERE event_id=?", (event["id"],)).fetchone()
                if existing:
                    previous_event = json.loads(existing["envelope"])
                    comparison = dict(event)
                    comparison["occurred_at"] = previous_event.get("occurred_at")
                    if previous_event != comparison:
                        raise ValueError("outbox event ID 内容冲突")
                else:
                    db.execute("INSERT INTO event_outbox(event_id,request_id,envelope,created) VALUES (?,?,?,?)",
                               (event["id"], request_id, encoded_event, now))
            if result.status not in {"unknown", "verification_pending", "partial", "abandoned"}:
                db.execute("DELETE FROM locks WHERE request_id=?", (request_id,))

    def pending_outbox(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            if db is None:
                return []
            rows = db.execute("SELECT envelope FROM event_outbox WHERE imported=0 ORDER BY created,event_id").fetchall()
        return [{"envelope": json.loads(row["envelope"])} for row in rows]

    def mark_outbox_imported(self, event_id: str) -> bool:
        if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
            raise ValueError("event_id 格式无效")
        with self.connect(write=True) as db:
            changed = db.execute(
                "UPDATE event_outbox SET imported=1,imported_at=? WHERE event_id=? AND imported=0",
                (_now(), event_id),
            ).rowcount
        return changed == 1

    def resolve(self, request_id: str, outcome: str, *, actor: str, reason_code: str,
                evidence_ref: str = "") -> dict[str, Any]:
        """Append an explicit human/readback resolution without replacing a receipt."""
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError("request_id 格式无效")
        if outcome not in {"verified_success", "verified_failed", "abandoned"}:
            raise ValueError("解析结果无效")
        if not isinstance(actor, str) or not _ID.fullmatch(actor):
            raise ValueError("actor 格式无效")
        if not isinstance(reason_code, str) or not _CODE.fullmatch(reason_code):
            raise ValueError("reason_code 格式无效")
        if not isinstance(evidence_ref, str) or len(evidence_ref) > 512 or any(ord(char) < 32 for char in evidence_ref):
            raise ValueError("evidence_ref 格式无效")
        safe_evidence = safe_resource_refs({"ref": evidence_ref}).get("ref", "") if evidence_ref else ""
        repeated = False
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            operation = db.execute("SELECT status,receipt FROM operations WHERE request_id=?", (request_id,)).fetchone()
            if operation is None:
                raise ValueError("找不到可解析的原请求")
            previous_resolution = db.execute(
                "SELECT outcome FROM receipt_resolutions WHERE request_id=? ORDER BY id DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            if previous_resolution:
                if previous_resolution["outcome"] != outcome:
                    raise ValueError("请求已经以不同结果解析")
                # Repeating the same human decision is idempotent.
                repeated = True
            else:
                original_receipt = json.loads(operation["receipt"]) if operation["receipt"] else None
                if operation["status"] in {"succeeded", "failed"} or (
                    isinstance(original_receipt, dict) and original_receipt.get("status") in {"succeeded", "failed"}
                ):
                    raise ValueError("明确成功或失败的收据不能再次解析")
                created = _now()
                db.execute("""
                    INSERT INTO receipt_resolutions(request_id,outcome,actor,reason_code,evidence_ref,created)
                    VALUES (?,?,?,?,?,?)
                """, (request_id, outcome, actor, reason_code, safe_evidence, created))
                if outcome == "verified_success":
                    db.execute("UPDATE operations SET status='succeeded',updated=? WHERE request_id=?", (created, request_id))
                    db.execute("DELETE FROM locks WHERE request_id=?", (request_id,))
                elif outcome == "verified_failed":
                    db.execute("UPDATE operations SET status='failed',updated=? WHERE request_id=?", (created, request_id))
                    db.execute("DELETE FROM locks WHERE request_id=?", (request_id,))
                else:
                    # Abandoning a check records the decision but keeps the resource lock.
                    db.execute("UPDATE operations SET status='abandoned',updated=? WHERE request_id=?", (created, request_id))
        value = self.effective_receipt(request_id)
        assert value is not None
        return value

    def effective_receipt(self, request_id: str) -> dict[str, Any] | None:
        value = self.receipt(request_id)
        if value is None:
            return None
        with self.connect() as db:
            if db is None:
                return None
            has_resolutions = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipt_resolutions'"
            ).fetchone()
            resolution = db.execute(
                "SELECT outcome,actor,reason_code,evidence_ref,created FROM receipt_resolutions WHERE request_id=? ORDER BY id DESC LIMIT 1",
                (request_id,),
            ).fetchone() if has_resolutions else None
        stored_receipt = value.get("receipt")
        original_receipt = dict(stored_receipt) if isinstance(stored_receipt, dict) else None
        original_status = original_receipt.get("status") if original_receipt else value["status"]
        value["original_status"] = original_status
        value["original_receipt"] = original_receipt
        if resolution is None:
            value["status"] = original_status
            value["resolution"] = None
            return value
        outcome = resolution["outcome"]
        effective_status = {"verified_success": "succeeded", "verified_failed": "failed", "abandoned": "abandoned"}[outcome]
        value["status"] = effective_status
        if original_receipt is not None:
            effective_receipt = dict(original_receipt)
            effective_receipt["status"] = effective_status
            if outcome == "verified_failed" and not effective_receipt.get("error"):
                effective_receipt["error"] = {"code": resolution["reason_code"]}
            value["receipt"] = effective_receipt
        value["resolution"] = dict(resolution)
        return value

    def claim_verification(self, request_id: str) -> bool:
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE operations SET status='verifying',updated=? WHERE request_id=? AND status='verification_pending'",
                                 (_now(), request_id)).rowcount
        return changed == 1

    def begin_plan(self, plan: Any, providers: dict[str, tuple[str, str]]) -> dict[str, Any]:
        """Persist references only; never store the user's step payloads in workflow history."""
        with self.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT fingerprint FROM workflow_runs WHERE plan_id=?", (plan.plan_id,)).fetchone()
            if current and current["fingerprint"] != plan.fingerprint:
                raise ValueError("plan_id 已关联到不同计划内容")
            if not current:
                now = _now()
                db.execute("INSERT INTO workflow_runs VALUES (?,?,?,?,?,?)",
                           (plan.plan_id, plan.fingerprint, plan.project_ref, "pending", now, now))
                for step in plan.steps:
                    provider, version = providers[step.step_id]
                    db.execute("INSERT INTO workflow_steps VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (plan.plan_id, step.step_id, step.capability, step.request.request_id,
                                json.dumps(list(step.depends_on)), provider, version, "pending", None, None, now))
            else:
                stored = db.execute("SELECT step_id,capability,request_id,depends_on,provider,provider_version FROM workflow_steps WHERE plan_id=? ORDER BY step_id", (plan.plan_id,)).fetchall()
                expected = sorted((s.step_id, s.capability, s.request.request_id, json.dumps(list(s.depends_on)), *providers[s.step_id]) for s in plan.steps)
                actual = sorted(tuple(row) for row in stored)
                if actual != expected:
                    raise ValueError("恢复计划的步骤、提供者或版本已变化")
        return self.workflow(plan.plan_id)

    def transition_step(self, plan_id: str, step_id: str, status: str, *, resource: dict[str, Any] | None = None, error_code: str | None = None) -> None:
        allowed = {"pending", "running", "succeeded", "failed", "unknown", "blocked", "partial", "verification_pending"}
        if status not in allowed:
            raise ValueError("流程步骤状态无效")
        resource_json = json.dumps(resource, ensure_ascii=False, sort_keys=True) if resource else None
        with self.connect(write=True) as db:
            db.execute("UPDATE workflow_steps SET status=?,result_refs=COALESCE(?,result_refs),error_code=?,updated=? WHERE plan_id=? AND step_id=?",
                       (status, resource_json, error_code, _now(), plan_id, step_id))
            db.execute("UPDATE workflow_runs SET updated=? WHERE plan_id=?", (_now(), plan_id))

    def finish_plan(self, plan_id: str, status: str) -> None:
        if status not in {"pending", "running", "succeeded", "failed", "partial", "unknown", "blocked"}:
            raise ValueError("流程状态无效")
        with self.connect(write=True) as db:
            db.execute("UPDATE workflow_runs SET status=?,updated=? WHERE plan_id=?", (status, _now(), plan_id))

    def workflow(self, plan_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            if db is None:
                return None
            has_workflows = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_runs'"
            ).fetchone()
            has_steps = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_steps'"
            ).fetchone()
            if not has_workflows or not has_steps:
                return None
            run = db.execute("SELECT * FROM workflow_runs WHERE plan_id=?", (plan_id,)).fetchone()
            if not run:
                return None
            steps = db.execute("SELECT * FROM workflow_steps WHERE plan_id=? ORDER BY step_id", (plan_id,)).fetchall()
        return {"run": dict(run), "steps": [
            {**dict(row), "depends_on": json.loads(row["depends_on"]), "result_refs": json.loads(row["result_refs"]) if row["result_refs"] else None}
            for row in steps
        ]}
