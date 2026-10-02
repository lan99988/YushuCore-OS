"""Shared operation receipts and privacy-minimized workflow checkpoints."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .contracts import Request


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def record(self, result: Any) -> None:
        receipt = result.to_dict()
        receipt["data"] = None
        with self.connect(write=True) as db:
            db.execute("UPDATE operations SET status=?,receipt=?,updated=? WHERE request_id=?", (
                result.status, json.dumps(receipt, ensure_ascii=False), _now(), result.request_id,
            ))
            if result.status not in {"unknown", "verification_pending", "partial"}:
                db.execute("DELETE FROM locks WHERE request_id=?", (result.request_id,))

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
