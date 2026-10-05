"""Metadata-only persistence for scheduled automation rules and runs."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Mapping

from yushuos_sdk.canonical import request_id as canonical_request_id, run_id as canonical_run_id
from yushuos_sdk.metadata import safe_resource_refs


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,99}$")
_ACTIVE = ("pending", "running", "host_pending", "unknown", "verification_pending")
_RUN_STATUSES = frozenset({
    "pending", "running", "host_pending", "unknown", "verification_pending",
    "succeeded", "failed", "blocked", "overlap_skipped", "abandoned", "misfire_skipped",
})
_TRIGGER_KEYS = frozenset({
    "kind", "type", "cron", "expression", "interval", "interval_seconds",
    "seconds", "anchor", "every", "at", "time", "timezone", "weekdays",
    "weekday", "day", "day_of_month", "month", "date", "start", "end",
    "source", "source_event", "event_type", "window", "jitter_seconds",
})
_RULE_KEYS = frozenset({
    "id", "rule_id", "revision", "enabled", "name", "action", "plugin_id",
    "action_ref", "action_hash", "pins", "trigger", "schedule", "project_ref",
    "timezone", "next_due", "last_scheduled", "misfire_policy",
    "grace_seconds", "misfire_window_seconds",
})


def _time(value: str | datetime, *, field: str = "时间") -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise ValueError(f"{field}必须是 ISO 8601 时间") from exc
    else:
        raise ValueError(f"{field}必须是 ISO 8601 时间")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field}必须使用 UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now() -> str:
    return _time(datetime.now(timezone.utc))


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label}格式无效")
    return value


def _revision(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("revision 必须是 JCS SHA-256 摘要")
    return value


def _error_code(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ValueError("error_code 必须是稳定的小写代码")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and (len(value) > 512 or any(ord(char) < 32 for char in value)):
            return None
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, (tuple, list)):
        return [_json_value(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, Mapping):
        return {
            key: _json_value(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
            if isinstance(key, str) and len(key) <= 64 and not key.lower() in {"fields", "data", "message", "error", "workflow", "payload", "steps"}
        }
    return None


def _pins(value: Any) -> Any:
    """Project provider pins and hashes while excluding action bodies."""
    if not isinstance(value, Mapping):
        raise ValueError("pins 必须是引用映射")
    if "steps" not in value and "providers" not in value:
        return {
            _identifier(key, "pin key"): _identifier(item, "pin value")
            for key, item in value.items()
        }

    def records(name: str, fields: frozenset[str], hashes: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        raw = value.get(name, [])
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"pins.{name} 必须是数组")
        output = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise ValueError(f"pins.{name} 项目格式无效")
            item: dict[str, Any] = {}
            for key, data in entry.items():
                if key not in fields:
                    continue
                if key in hashes:
                    if not isinstance(data, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", data):
                        raise ValueError(f"pins.{name}.{key} 必须是 SHA-256 摘要")
                    item[key] = data.lower()
                elif key == "permissions":
                    if not isinstance(data, (list, tuple)) or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in data):
                        raise ValueError("pins.steps.permissions 格式无效")
                    item[key] = sorted(set(data))
                else:
                    item[key] = _identifier(data, f"pins.{name}.{key}")
            output.append(item)
        return output

    steps = records("steps", frozenset({
        "step_id", "plugin_id", "version", "provider_digest", "capability", "intent",
        "effect", "execution_mode", "permissions", "resource_hash", "target_hash",
    }), frozenset({"provider_digest", "resource_hash", "target_hash"}))
    providers = records("providers", frozenset({"plugin_id", "version", "provider_digest"}),
                        frozenset({"provider_digest"}))
    return {"steps": steps, "providers": providers}


def _rule_value(rule: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(rule, Mapping):
        raise ValueError("rule 必须是对象")
    rule_id = _identifier(rule.get("id", rule.get("rule_id")), "rule_id")
    revision = _revision(rule.get("revision"))
    enabled = rule.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")

    action = rule.get("action")
    if action is None:
        action = {"plugin_id": rule.get("plugin_id"), "action_ref": rule.get("action_ref")}
    if not isinstance(action, Mapping):
        raise ValueError("action 必须是引用对象")
    action_value = {
        key: _identifier(action.get(key), f"action.{key}")
        for key in ("plugin_id", "action_ref")
        if action.get(key) is not None
    }
    if not action_value.get("plugin_id") or not action_value.get("action_ref"):
        raise ValueError("action 必须包含 plugin_id 和 action_ref")

    action_hash = rule.get("action_hash", "")
    if action_hash and (not isinstance(action_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", action_hash)):
        raise ValueError("action_hash 必须是 SHA-256 十六进制摘要")
    pins = _pins(rule.get("pins", {}))

    trigger = rule.get("trigger", rule.get("schedule"))
    if isinstance(trigger, Mapping):
        trigger = {
            key: _json_value(value)
            for key, value in trigger.items()
            if isinstance(key, str) and key in _TRIGGER_KEYS
        }
    elif trigger is not None and not isinstance(trigger, str):
        raise ValueError("trigger 必须是字符串或调度元数据对象")
    if isinstance(trigger, str) and (len(trigger) > 512 or any(ord(char) < 32 for char in trigger)):
        raise ValueError("trigger 格式无效")

    project_ref = rule.get("project_ref", "")
    if not isinstance(project_ref, str) or len(project_ref) > 200:
        raise ValueError("project_ref 格式无效")
    name = rule.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > 200 or any(ord(char) < 32 for char in name)):
        raise ValueError("name 格式无效")
    next_due = _time(rule["next_due"], field="next_due") if rule.get("next_due") is not None else None
    last_scheduled = _time(rule["last_scheduled"], field="last_scheduled") if rule.get("last_scheduled") is not None else None
    timezone_name = rule.get("timezone")
    if timezone_name is not None and (not isinstance(timezone_name, str) or len(timezone_name) > 100):
        raise ValueError("timezone 格式无效")

    misfire_policy = rule.get("misfire_policy", "skip")
    if misfire_policy not in {"skip", "latest"}:
        raise ValueError("misfire_policy 无效")
    grace_seconds = rule.get("grace_seconds", 60)
    misfire_window_seconds = rule.get("misfire_window_seconds", 3600)
    if any(type(seconds) is not int or not 1 <= seconds <= 86400
           for seconds in (grace_seconds, misfire_window_seconds)):
        raise ValueError("misfire seconds 格式无效")

    result: dict[str, Any] = {
        "id": rule_id, "revision": revision, "enabled": enabled,
        "action": action_value, "action_hash": action_hash.lower(), "pins": pins,
        "trigger": trigger, "project_ref": project_ref,
        "next_due": next_due, "last_scheduled": last_scheduled,
        "misfire_policy": misfire_policy, "grace_seconds": grace_seconds,
        "misfire_window_seconds": misfire_window_seconds,
    }
    if name is not None:
        result["name"] = name
    if timezone_name is not None:
        result["timezone"] = timezone_name
    # This explicit projection prevents request fields or workflow bodies from
    # entering the automation database even when callers pass a larger object.
    return {key: value for key, value in result.items() if key in _RULE_KEYS}


class AutomationStore:
    """Persist scheduling metadata and execution references in a separate SQLite DB."""

    def __init__(self, path: str | Path):
        supplied = Path(path).expanduser()
        if supplied.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
            self.path = supplied.absolute()
        else:
            self.path = (supplied / "automation.sqlite").absolute()
        self._prepare()

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS automation_rules (
                    rule_id TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    metadata_json TEXT NOT NULL,
                    next_due TEXT,
                    last_scheduled TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_grants (
                    rule_id TEXT PRIMARY KEY,
                    grant_json TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(rule_id) REFERENCES automation_rules(rule_id)
                );
                CREATE TABLE IF NOT EXISTS automation_events (
                    event_id TEXT PRIMARY KEY,
                    envelope_json TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0 CHECK(delivered IN (0,1)),
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    purged INTEGER NOT NULL DEFAULT 0 CHECK(purged IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS automation_runs (
                    run_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    occurrence_key TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    event_id TEXT,
                    root_event_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '',
                    resource_refs_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    generation INTEGER NOT NULL DEFAULT 0,
                    dispatched INTEGER NOT NULL DEFAULT 0 CHECK(dispatched IN (0,1)),
                    purged INTEGER NOT NULL DEFAULT 0 CHECK(purged IN (0,1)),
                    resolution_json TEXT,
                    resolved_from TEXT,
                    rule_snapshot_json TEXT,
                    authorization_json TEXT,
                    UNIQUE(rule_id, revision, occurrence_key)
                );
                CREATE INDEX IF NOT EXISTS automation_runs_rule_status
                    ON automation_runs(rule_id, status);
                CREATE INDEX IF NOT EXISTS automation_runs_root
                    ON automation_runs(root_event_id);
                CREATE TABLE IF NOT EXISTS automation_run_steps (
                    request_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    project_ref TEXT NOT NULL,
                    UNIQUE(run_id,step_id)
                );
                CREATE INDEX IF NOT EXISTS automation_run_steps_lookup
                    ON automation_run_steps(request_id,project_ref);
                CREATE TABLE IF NOT EXISTS root_budgets (
                    root_event_id TEXT PRIMARY KEY,
                    run_count INTEGER NOT NULL CHECK(run_count BETWEEN 0 AND 256),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_run_authorizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    grant_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS automation_run_authorizations_run
                    ON automation_run_authorizations(run_id,id);
            """)
            # Keep databases created by an earlier local build readable.
            for table, columns in {
                "automation_events": {"purged": "INTEGER NOT NULL DEFAULT 0"},
                "automation_runs": {
                    "purged": "INTEGER NOT NULL DEFAULT 0",
                    "resolution_json": "TEXT",
                    "resolved_from": "TEXT",
                    "rule_snapshot_json": "TEXT",
                    "authorization_json": "TEXT",
                },
            }.items():
                existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, declaration in columns.items():
                    if name not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _rule_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = json.loads(row["metadata_json"])
        value.update({
            "id": row["rule_id"], "revision": row["revision"],
            "enabled": bool(row["enabled"]), "next_due": row["next_due"],
            "last_scheduled": row["last_scheduled"],
        })
        return value

    @staticmethod
    def _run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value["resource_refs"] = json.loads(value.pop("resource_refs_json"))
        value["dispatched"] = bool(value["dispatched"])
        value["purged"] = bool(value.get("purged", 0))
        resolution = value.pop("resolution_json", None)
        value["resolution"] = json.loads(resolution) if resolution else None
        snapshot = value.pop("rule_snapshot_json", None)
        value["rule_snapshot"] = json.loads(snapshot) if snapshot else None
        authorization = value.pop("authorization_json", None)
        value["authorization"] = json.loads(authorization) if authorization else None
        value["authorization_history"] = []
        value["lease_generation"] = value["generation"]
        return value

    def put_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        value = _rule_value(rule)
        rule_id = value["id"]
        metadata = dict(value)
        for key in ("id", "revision", "enabled", "next_due", "last_scheduled"):
            metadata.pop(key, None)
        timestamp = _now()
        with self._connection(write=True) as db:
            old = db.execute("SELECT * FROM automation_rules WHERE rule_id=?", (rule_id,)).fetchone()
            if old and old["revision"] == value["revision"]:
                previous = json.loads(old["metadata_json"])
                if previous != metadata:
                    raise ValueError("同一 revision 的规则动作或触发元数据不可修改")
            db.execute("""
                INSERT INTO automation_rules(rule_id,revision,enabled,metadata_json,next_due,last_scheduled,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    revision=excluded.revision, enabled=excluded.enabled,
                    metadata_json=excluded.metadata_json, next_due=excluded.next_due,
                    last_scheduled=excluded.last_scheduled, updated_at=excluded.updated_at
            """, (rule_id, value["revision"], int(value["enabled"]), _json(metadata), value["next_due"],
                  value["last_scheduled"], timestamp, timestamp))
            row = db.execute("SELECT * FROM automation_rules WHERE rule_id=?", (rule_id,)).fetchone()
        return self._rule_row(row)  # type: ignore[return-value]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        rule_id = _identifier(rule_id, "rule_id")
        with self._connection() as db:
            row = db.execute("SELECT * FROM automation_rules WHERE rule_id=?", (rule_id,)).fetchone()
        return self._rule_row(row)

    def list_rules(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM automation_rules ORDER BY rule_id").fetchall()
        return [self._rule_row(row) for row in rows if row is not None]  # type: ignore[list-item]

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        rule_id = _identifier(rule_id, "rule_id")
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        with self._connection(write=True) as db:
            changed = db.execute("UPDATE automation_rules SET enabled=?,updated_at=? WHERE rule_id=?",
                                 (int(enabled), _now(), rule_id)).rowcount
        return changed == 1

    def update_cursor(self, rule_id: str, revision: int, next_due: str | datetime | None) -> bool:
        rule_id = _identifier(rule_id, "rule_id")
        revision = _revision(revision)
        normalized = _time(next_due, field="next_due") if next_due is not None else None
        with self._connection(write=True) as db:
            changed = db.execute(
                "UPDATE automation_rules SET next_due=?,updated_at=? WHERE rule_id=? AND revision=?",
                (normalized, _now(), rule_id, revision),
            ).rowcount
        return changed == 1

    def save_grant(self, rule_id: str, grant: dict[str, Any]) -> dict[str, Any]:
        rule_id = _identifier(rule_id, "rule_id")
        if not isinstance(grant, Mapping):
            raise ValueError("grant 必须是对象")
        grant_id = _identifier(grant.get("grant_id", grant.get("id")), "grant_id")
        expires = grant.get("expires_at", grant.get("expires"))
        if expires is None:
            raise ValueError("grant 必须包含 expires_at")
        safe_grant: dict[str, Any] = {
            "grant_id": grant_id, "expires_at": _time(expires, field="expires_at"),
        }
        scopes = grant.get("scopes", [])
        if not isinstance(scopes, (list, tuple)) or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in scopes):
            raise ValueError("grant scopes 格式无效")
        safe_grant["scopes"] = sorted(set(scopes))
        if grant.get("rule_id") is not None and grant["rule_id"] != rule_id:
            raise ValueError("grant rule_id 不匹配")
        if grant.get("revision") is not None:
            safe_grant["revision"] = _revision(grant["revision"])
        if grant.get("action_hash") is not None:
            action_hash = grant["action_hash"]
            if not isinstance(action_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", action_hash):
                raise ValueError("grant action_hash 格式无效")
            safe_grant["action_hash"] = action_hash.lower()
        if grant.get("pins") is not None:
            safe_grant["pins"] = _pins(grant["pins"])
        if grant.get("created_at") is not None:
            safe_grant["created_at"] = _time(grant["created_at"], field="created_at")
        if grant.get("canonicalization") is not None:
            safe_grant["canonicalization"] = _identifier(grant["canonicalization"], "canonicalization")
        for key in ("actor", "source"):
            if key in grant:
                safe_grant[key] = _identifier(grant[key], key)
        with self._connection(write=True) as db:
            if not db.execute("SELECT 1 FROM automation_rules WHERE rule_id=?", (rule_id,)).fetchone():
                raise ValueError("找不到授权对应的规则")
            db.execute("""
                INSERT INTO automation_grants(rule_id,grant_json,revoked,updated_at) VALUES (?,?,0,?)
                ON CONFLICT(rule_id) DO UPDATE SET grant_json=excluded.grant_json,revoked=0,updated_at=excluded.updated_at
            """, (rule_id, _json(safe_grant), _now()))
        return safe_grant

    def active_grant(self, rule_id: str, now: str | datetime) -> dict[str, Any] | None:
        rule_id = _identifier(rule_id, "rule_id")
        normalized_now = _time(now, field="now")
        with self._connection() as db:
            row = db.execute("SELECT grant_json,revoked FROM automation_grants WHERE rule_id=?", (rule_id,)).fetchone()
        if row is None or row["revoked"]:
            return None
        grant = json.loads(row["grant_json"])
        return grant if normalized_now < grant["expires_at"] else None

    def revoke(self, rule_id: str) -> bool:
        rule_id = _identifier(rule_id, "rule_id")
        with self._connection(write=True) as db:
            changed = db.execute("UPDATE automation_grants SET revoked=1,updated_at=? WHERE rule_id=?",
                                 (_now(), rule_id)).rowcount
        return changed == 1

    def publish_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise ValueError("event 必须是对象")
        event_id = _identifier(event.get("id"), "event.id")
        event_type = _identifier(event.get("type"), "event.type")
        source_plugin = _identifier(event.get("source_plugin"), "event.source_plugin")
        source_version = _identifier(event.get("source_version"), "event.source_version")
        has_provider_digest = "provider_digest" in event
        provider_digest = event.get("provider_digest")
        if has_provider_digest and (
            not isinstance(provider_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", provider_digest)
        ):
            raise ValueError("event.provider_digest 格式无效")
        request_id = event.get("request_id", "")
        if not isinstance(request_id, str) or len(request_id) > 200 or any(ord(char) < 32 for char in request_id):
            raise ValueError("event.request_id 格式无效")
        project_ref = event.get("project_ref", "")
        if not isinstance(project_ref, str) or len(project_ref) > 200:
            raise ValueError("event.project_ref 格式无效")
        depth = event.get("depth", 0)
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("event.depth 格式无效")
        causation_id = event.get("causation_id") or ""
        root_event_id = event.get("root_event_id") or ""
        if causation_id:
            _identifier(causation_id, "event.causation_id")
        if root_event_id:
            _identifier(root_event_id, "event.root_event_id")
        envelope = {
            "id": event_id, "type": event_type, "source_plugin": source_plugin,
            "source_version": source_version, "project_ref": project_ref,
            "request_id": request_id, "causation_id": causation_id,
            "root_event_id": root_event_id,
            "occurred_at": _time(event.get("occurred_at"), field="event.occurred_at"),
            "depth": depth, "resource_refs": safe_resource_refs(event.get("resource_refs", {})),
        }
        if has_provider_digest:
            envelope["provider_digest"] = provider_digest
        body = _json(envelope)
        with self._connection(write=True) as db:
            old = db.execute("SELECT envelope_json,purged FROM automation_events WHERE event_id=?", (event_id,)).fetchone()
            if old:
                previous = json.loads(old["envelope_json"])
                if old["purged"]:
                    # A purged delivered event keeps its identity tombstone. An
                    # old duplicate cannot republish its removed references.
                    keys = ("id", "type", "source_plugin", "source_version", "project_ref", "request_id",
                            "causation_id", "root_event_id", "occurred_at", "depth", "provider_digest")
                    if any(previous.get(key) != envelope.get(key) for key in keys):
                        raise ValueError("事件 ID 冲突")
                    envelope = previous
                elif old["envelope_json"] != body:
                    raise ValueError("事件 ID 冲突")
            else:
                db.execute("INSERT INTO automation_events(event_id,envelope_json,created_at) VALUES (?,?,?)",
                           (event_id, body, _now()))
        return envelope

    def pending_events(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT envelope_json FROM automation_events WHERE delivered=0 ORDER BY created_at,event_id").fetchall()
        return [json.loads(row["envelope_json"]) for row in rows]

    def show_event(self, event_id: str) -> dict[str, Any] | None:
        event_id = _identifier(event_id, "event_id")
        with self._connection() as db:
            row = db.execute(
                "SELECT envelope_json,delivered,created_at,delivered_at,purged FROM automation_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **json.loads(row["envelope_json"]), "delivered": bool(row["delivered"]),
            "created_at": row["created_at"], "delivered_at": row["delivered_at"], "purged": bool(row["purged"]),
        }

    def list_events(self, *, limit: int = 100, delivered: bool | None = None) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit 必须在 1 到 1000 之间")
        if delivered is not None and not isinstance(delivered, bool):
            raise ValueError("delivered 必须是布尔值")
        where = " WHERE delivered=?" if delivered is not None else ""
        params = (int(delivered), limit) if delivered is not None else (limit,)
        with self._connection() as db:
            rows = db.execute(
                f"SELECT envelope_json,delivered,created_at,delivered_at,purged FROM automation_events{where} ORDER BY created_at DESC,event_id LIMIT ?",
                params,
            ).fetchall()
        return [
            {**json.loads(row["envelope_json"]), "delivered": bool(row["delivered"]),
             "created_at": row["created_at"], "delivered_at": row["delivered_at"], "purged": bool(row["purged"])}
            for row in rows
        ]

    def mark_event_delivered(self, event_id: str) -> bool:
        event_id = _identifier(event_id, "event_id")
        with self._connection(write=True) as db:
            changed = db.execute("UPDATE automation_events SET delivered=1,delivered_at=? WHERE event_id=? AND delivered=0",
                                 (_now(), event_id)).rowcount
        return changed == 1

    def enqueue_run(self, rule: dict[str, Any], occurrence_key: str,
                    scheduled_at: str | datetime, root_event_id: str | None = None,
                    depth: int = 0) -> dict[str, Any]:
        value = _rule_value(rule)
        rule_id = value["id"]
        revision = value["revision"]
        occurrence_key = _identifier(occurrence_key, "occurrence_key")
        scheduled = _time(scheduled_at, field="scheduled_at")
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("depth 必须是非负整数")
        run_id = canonical_run_id(rule_id, revision, occurrence_key)
        root_id = _identifier(root_event_id, "root_event_id") if root_event_id else run_id
        timestamp = _now()
        rule_snapshot = {
            key: item for key, item in value.items()
            if key not in {"enabled", "next_due", "last_scheduled"}
        }
        with self._connection(write=True) as db:
            stored_rule = db.execute("SELECT revision FROM automation_rules WHERE rule_id=?", (rule_id,)).fetchone()
            if stored_rule is None or stored_rule["revision"] != revision:
                raise ValueError("rule revision 尚未保存或已变化")
            old = db.execute(
                "SELECT * FROM automation_runs WHERE rule_id=? AND revision=? AND occurrence_key=?",
                (rule_id, revision, occurrence_key),
            ).fetchone()
            if old:
                duplicate = self._run_row(old)
                history = db.execute(
                    "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id",
                    (duplicate["run_id"],),
                ).fetchall()
                duplicate["authorization_history"] = [json.loads(item["grant_json"]) for item in history]
                return duplicate
            collision = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if collision:
                raise ValueError("canonical run_id 已关联其他运行")

            budget = db.execute("SELECT run_count FROM root_budgets WHERE root_event_id=?", (root_id,)).fetchone()
            count = budget["run_count"] if budget else 0
            error_code = ""
            if depth > 8:
                status, error_code = "blocked", "depth_limit"
            elif count >= 256:
                status, error_code = "blocked", "fanout_limit"
            else:
                overlapping = db.execute(
                    f"SELECT 1 FROM automation_runs WHERE rule_id=? AND status IN ({','.join('?' for _ in _ACTIVE)}) LIMIT 1",
                    (rule_id, *_ACTIVE),
                ).fetchone()
                status = "overlap_skipped" if overlapping else "pending"
                if overlapping:
                    error_code = "overlap_skipped"
            if count < 256:
                new_count = count + 1
                db.execute("""
                    INSERT INTO root_budgets(root_event_id,run_count,updated_at) VALUES (?,?,?)
                    ON CONFLICT(root_event_id) DO UPDATE SET run_count=excluded.run_count,updated_at=excluded.updated_at
                """, (root_id, new_count, timestamp))
            event_id = occurrence_key[6:] if occurrence_key.startswith("event:") else None
            if event_id is not None:
                event_id = _identifier(event_id, "event_id")
            db.execute("""
                INSERT INTO automation_runs(
                    run_id,rule_id,revision,occurrence_key,scheduled_at,event_id,root_event_id,depth,status,error_code,
                    resource_refs_json,created_at,updated_at,rule_snapshot_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (run_id, rule_id, revision, occurrence_key, scheduled, event_id, root_id, depth,
                  status, error_code, "{}", timestamp, timestamp, _json(rule_snapshot)))
            pins = value.get("pins", {})
            step_pins = pins.get("steps", []) if isinstance(pins, Mapping) else []
            if isinstance(step_pins, list):
                for step in step_pins:
                    if isinstance(step, Mapping) and isinstance(step.get("step_id"), str):
                        step_id = _identifier(step["step_id"], "step_id")
                        db.execute(
                            "INSERT INTO automation_run_steps(request_id,run_id,step_id,project_ref) VALUES (?,?,?,?)",
                            (canonical_request_id(run_id, step_id), run_id, step_id, value["project_ref"]),
                        )
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_row(row)  # type: ignore[return-value]

    def claim_run(self, run_id: str, owner: str, now: str | datetime, ttl: int | float = 30) -> dict[str, Any] | None:
        run_id = _identifier(run_id, "run_id")
        owner = _identifier(owner, "owner")
        normalized_now = _time(now, field="now")
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError("ttl 必须是正数")
        expires = _time(datetime.fromisoformat(normalized_now.replace("Z", "+00:00")) + timedelta(seconds=ttl))
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            status = row["status"]
            if status == "running":
                expiry = row["lease_expires_at"]
                if expiry is None or normalized_now < expiry:
                    return None
                if row["dispatched"]:
                    db.execute("UPDATE automation_runs SET status='unknown',error_code='dispatched_lease_expired',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
                               (normalized_now, run_id))
                    return None
            elif status not in {"pending", "host_pending"}:
                return None
            generation = row["generation"] + 1
            db.execute("""
                UPDATE automation_runs SET status='running',lease_owner=?,lease_expires_at=?,generation=?,updated_at=?
                WHERE run_id=?
            """, (owner, expires, generation, normalized_now, run_id))
            result = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_row(result)

    @staticmethod
    def _require_lease(row: sqlite3.Row | None, owner: str, generation: int,
                       now: str) -> sqlite3.Row:
        if row is None or row["status"] != "running" or row["lease_owner"] != owner or row["generation"] != generation:
            raise ValueError("租约所有者或 generation 已失效")
        if not row["lease_expires_at"] or now >= row["lease_expires_at"]:
            raise ValueError("租约已过期")
        return row

    def renew_lease(self, run_id: str, owner: str, generation: int,
                    now: str | datetime, ttl: int | float = 30) -> bool:
        run_id, owner = _identifier(run_id, "run_id"), _identifier(owner, "owner")
        normalized_now = _time(now, field="now")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation 格式无效")
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError("ttl 必须是正数")
        expires = _time(datetime.fromisoformat(normalized_now.replace("Z", "+00:00")) + timedelta(seconds=ttl))
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            self._require_lease(row, owner, generation, normalized_now)
            db.execute("UPDATE automation_runs SET lease_expires_at=?,updated_at=? WHERE run_id=?",
                       (expires, normalized_now, run_id))
        return True

    def mark_dispatched(self, run_id: str, owner: str, generation: int,
                        now: str | datetime) -> bool:
        run_id, owner = _identifier(run_id, "run_id"), _identifier(owner, "owner")
        normalized_now = _time(now, field="now")
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            self._require_lease(row, owner, generation, normalized_now)
            db.execute("UPDATE automation_runs SET dispatched=1,updated_at=? WHERE run_id=?",
                       (normalized_now, run_id))
        return True

    def set_run_authorization(self, run_id: str, grant: dict[str, Any], *,
                              owner: str | None = None, generation: int | None = None,
                              now: str | datetime | None = None) -> dict[str, Any]:
        """Freeze the exact grant metadata used when this run is authorized."""
        run_id = _identifier(run_id, "run_id")
        if not isinstance(grant, Mapping):
            raise ValueError("grant 必须是对象")
        safe: dict[str, Any] = {
            "grant_id": _identifier(grant.get("grant_id"), "grant_id"),
            "expires_at": _time(grant.get("expires_at"), field="expires_at"),
            "revision": _revision(grant.get("revision")),
            "action_hash": grant.get("action_hash"),
            "pins": _pins(grant.get("pins")),
        }
        if not isinstance(safe["action_hash"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", safe["action_hash"]):
            raise ValueError("grant action_hash 格式无效")
        safe["action_hash"] = safe["action_hash"].lower()
        if grant.get("created_at") is not None:
            safe["created_at"] = _time(grant["created_at"], field="created_at")
        if grant.get("canonicalization") is not None:
            safe["canonicalization"] = _identifier(grant["canonicalization"], "canonicalization")
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("找不到自动化 run")
            if not row["rule_snapshot_json"]:
                raise ValueError("run 缺少可核验的规则快照")
            if any(item is not None for item in (owner, generation, now)):
                if owner is None or generation is None or now is None:
                    raise ValueError("lease CAS 需要 owner、generation 和 now")
                owner = _identifier(owner, "owner")
                if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
                    raise ValueError("generation 格式无效")
                self._require_lease(row, owner, generation, _time(now, field="now"))
            snapshot = json.loads(row["rule_snapshot_json"])
            if any(snapshot.get(key) != safe.get(key) for key in ("revision", "action_hash", "pins")):
                raise ValueError("grant 与 run 规则快照不匹配")
            encoded = _json(safe)
            previous = db.execute(
                "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if previous and previous["grant_json"] == encoded:
                return safe
            if row["authorization_json"]:
                original = json.loads(row["authorization_json"])
                if any(original.get(key) != safe.get(key) for key in ("revision", "action_hash", "pins")):
                    raise ValueError("run 授权的规则绑定不可改变")
            else:
                db.execute("UPDATE automation_runs SET authorization_json=? WHERE run_id=?", (encoded, run_id))
            db.execute(
                "INSERT INTO automation_run_authorizations(run_id,grant_json,created_at) VALUES (?,?,?)",
                (run_id, encoded, _now()),
            )
        return safe

    def resolve_run(self, run_id: str, status: str, *, actor: str,
                    reason_code: str, evidence_ref: str = "") -> dict[str, Any]:
        """Append an explicit resolution while retaining the original run status."""
        run_id = _identifier(run_id, "run_id")
        if status not in {"verified_success", "verified_failed", "abandoned"}:
            raise ValueError("run resolution status 无效")
        actor = _identifier(actor, "actor")
        reason_code = _error_code(reason_code)
        if not reason_code:
            raise ValueError("reason_code 无效")
        if not isinstance(evidence_ref, str) or len(evidence_ref) > 512 or any(ord(char) < 32 for char in evidence_ref):
            raise ValueError("evidence_ref 格式无效")
        evidence = safe_resource_refs({"ref": evidence_ref}).get("ref", "") if evidence_ref else ""
        with self._connection(write=True) as db:
            row = db.execute("SELECT status,resolution_json FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("找不到可解析的自动化 run")
            if row["resolution_json"]:
                previous = json.loads(row["resolution_json"])
                if previous["status"] != status:
                    raise ValueError("run 已经以不同结果解析")
            else:
                if row["status"] not in {"unknown", "verification_pending", "abandoned"}:
                    raise ValueError("只有结果未决的 run 可以解析")
                resolution = {
                    "status": status, "actor": actor, "reason_code": reason_code,
                    "evidence_ref": evidence, "resolved_at": _now(), "resolved_from": row["status"],
                }
                db.execute("UPDATE automation_runs SET resolution_json=? WHERE run_id=?", (_json(resolution), run_id))
        return self.show_run(run_id)  # type: ignore[return-value]

    def release_resolved_run(self, run_id: str) -> bool:
        """Make a human-verified unknown run pending for explicit workflow continuation."""
        run_id = _identifier(run_id, "run_id")
        with self._connection(write=True) as db:
            row = db.execute("SELECT status,resolution_json FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "unknown" or not row["resolution_json"]:
                return False
            resolution = json.loads(row["resolution_json"])
            if resolution.get("status") not in {"verified_success", "verified_failed"}:
                return False
            db.execute("""
                UPDATE automation_runs SET status='pending',resolved_from=?,dispatched=0,
                    lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?
            """, (row["status"], _now(), run_id))
        return True

    def update_run(self, run_id: str, owner: str, generation: int, status: str,
                   now: str | datetime, error_code: str = "",
                   resource_refs: dict[str, Any] | None = None) -> bool:
        run_id, owner = _identifier(run_id, "run_id"), _identifier(owner, "owner")
        normalized_now = _time(now, field="now")
        if status not in _RUN_STATUSES:
            raise ValueError("run status 无效")
        safe_code = _error_code(error_code)
        refs_json = _json(safe_resource_refs(resource_refs or {}))
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            self._require_lease(row, owner, generation, normalized_now)
            db.execute("""
                UPDATE automation_runs SET status=?,error_code=?,resource_refs_json=?,updated_at=?,
                    lease_owner=NULL,lease_expires_at=NULL
                WHERE run_id=?
            """, (status, safe_code, refs_json, normalized_now, run_id))
        return True

    def show_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = _identifier(run_id, "run_id")
        with self._connection() as db:
            row = db.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            result = self._run_row(row)
            history = db.execute(
                "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
            result["authorization_history"] = [json.loads(item["grant_json"]) for item in history]
        return result

    def release_host_pending(self, run_id: str) -> bool:
        """Release a host-pending run only after the caller explicitly chooses it."""
        run_id = _identifier(run_id, "run_id")
        with self._connection(write=True) as db:
            changed = db.execute(
                "UPDATE automation_runs SET status='pending',updated_at=? WHERE run_id=? AND status='host_pending'",
                (_now(), run_id),
            ).rowcount
        return changed == 1

    def purge_history(self, before: str | datetime, *, rule_id: str | None = None) -> dict[str, int]:
        """Clear expired resource references while retaining dedupe tombstones."""
        cutoff = _time(before, field="before")
        clauses = ["updated_at<?", "purged=0", "status IN ('succeeded','failed','blocked','overlap_skipped','misfire_skipped')"]
        params: list[Any] = [cutoff]
        if rule_id is not None:
            clauses.append("rule_id=?")
            params.append(_identifier(rule_id, "rule_id"))
        with self._connection(write=True) as db:
            runs = db.execute(f"SELECT run_id FROM automation_runs WHERE {' AND '.join(clauses)}", params).fetchall()
            for row in runs:
                db.execute("UPDATE automation_runs SET resource_refs_json='{}',purged=1 WHERE run_id=?", (row["run_id"],))
            events = db.execute(
                "SELECT event_id,envelope_json FROM automation_events WHERE delivered=1 AND created_at<? AND purged=0",
                (cutoff,),
            ).fetchall()
            for row in events:
                envelope = json.loads(row["envelope_json"])
                envelope["resource_refs"] = {}
                db.execute("UPDATE automation_events SET envelope_json=?,purged=1 WHERE event_id=?",
                           (_json(envelope), row["event_id"]))
        return {"runs_purged": len(runs), "events_purged": len(events)}

    def list_runs(self, *, rule_id: str | None = None, status: str | None = None,
                  limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit 必须在 1 到 1000 之间")
        clauses: list[str] = []
        params: list[Any] = []
        if rule_id is not None:
            clauses.append("rule_id=?")
            params.append(_identifier(rule_id, "rule_id"))
        if status is not None:
            if status not in _RUN_STATUSES:
                raise ValueError("run status 无效")
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as db:
            rows = db.execute(f"SELECT * FROM automation_runs{where} ORDER BY created_at DESC,run_id DESC LIMIT ?",
                               (*params, limit)).fetchall()
            results = []
            for row in rows:
                value = self._run_row(row)
                history = db.execute(
                    "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id",
                    (value["run_id"],),
                ).fetchall()
                value["authorization_history"] = [json.loads(item["grant_json"]) for item in history]
                results.append(value)
        return results

    def find_runs_for_request(self, request_id: str, project_ref: str) -> list[dict[str, Any]]:
        """Find every frozen run step that owns a shared-ledger request ID."""
        request_id = _identifier(request_id, "request_id")
        if not isinstance(project_ref, str) or len(project_ref) > 200:
            raise ValueError("project_ref 格式无效")
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        with self._connection() as db:
            rows = db.execute("""
                SELECT r.*,s.step_id AS matched_step_id
                FROM automation_run_steps s
                JOIN automation_runs r ON r.run_id=s.run_id
                WHERE s.request_id=? AND s.project_ref=?
                ORDER BY r.created_at,r.run_id,s.step_id
            """, (request_id, project_ref)).fetchall()
            for row in rows:
                value = self._run_row(row)
                step_id = value.pop("matched_step_id")
                seen.add((value["run_id"], step_id))
                history = db.execute(
                    "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id",
                    (value["run_id"],),
                ).fetchall()
                value["authorization_history"] = [json.loads(item["grant_json"]) for item in history]
                matches.append({"run": value, "step_id": step_id})

            # Compatibility scan for old runs written before the indexed mapping
            # existed. It has no fixed history cap and never rebuilds action bodies.
            legacy = db.execute("""
                SELECT * FROM automation_runs
                WHERE rule_snapshot_json IS NOT NULL
                  AND run_id NOT IN (SELECT run_id FROM automation_run_steps)
                ORDER BY created_at,run_id
            """).fetchall()
            for row in legacy:
                snapshot = json.loads(row["rule_snapshot_json"])
                if snapshot.get("project_ref", "") != project_ref:
                    continue
                pins = snapshot.get("pins", {})
                steps = pins.get("steps", []) if isinstance(pins, dict) else []
                value = self._run_row(row)
                for step in steps:
                    if not isinstance(step, dict) or not isinstance(step.get("step_id"), str):
                        continue
                    step_id = step["step_id"]
                    try:
                        matches_request = canonical_request_id(value["run_id"], step_id) == request_id
                    except ValueError:
                        continue
                    if matches_request and (value["run_id"], step_id) not in seen:
                        history = db.execute(
                            "SELECT grant_json FROM automation_run_authorizations WHERE run_id=? ORDER BY id",
                            (value["run_id"],),
                        ).fetchall()
                        value["authorization_history"] = [json.loads(item["grant_json"]) for item in history]
                        matches.append({"run": value, "step_id": step_id})
                        seen.add((value["run_id"], step_id))
        return matches


__all__ = ["AutomationStore"]
