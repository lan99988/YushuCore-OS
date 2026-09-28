"""One-use, expiring human approvals bound to an exact local action."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any
from uuid import uuid4

from .profile import Profile


class ApprovalError(ValueError):
    pass


class ApprovalStore:
    def __init__(self, profile: Profile) -> None:
        self.path = profile.database_path
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS app_approvals (
                approval_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                target TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(agent_id, capability, payload_digest, correlation_id)
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _serialized(payload: dict[str, Any]) -> tuple[str, str]:
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return content, hashlib.sha256(content.encode("utf-8")).hexdigest()

    def request(self, *, agent_id: str, capability: str, payload: dict[str, Any],
                correlation_id: str, target: str, lifetime_minutes: int = 15) -> str:
        content, digest = self._serialized(payload)
        now = datetime.now(timezone.utc)
        approval_id = uuid4().hex
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO app_approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (approval_id, agent_id, capability, content, digest, target, correlation_id,
                 (now + timedelta(minutes=lifetime_minutes)).isoformat(), "pending", now.isoformat()))
            row = db.execute("SELECT approval_id FROM app_approvals WHERE agent_id=? AND capability=? "
                "AND payload_digest=? AND correlation_id=?",
                (agent_id, capability, digest, correlation_id)).fetchone()
            assert row is not None
            return row["approval_id"]

    def list_pending(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT approval_id, agent_id, capability, payload_json, payload_digest, "
                "target, correlation_id, expires_at, created_at FROM app_approvals "
                "WHERE status='pending' ORDER BY created_at").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def claim(self, approval_id: str, *, reviewer: str) -> dict[str, Any]:
        if reviewer != "owner":
            raise ApprovalError("owner_approval_required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM app_approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None or row["status"] != "pending":
                raise ApprovalError("approval_not_pending")
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                db.execute("UPDATE app_approvals SET status='expired' WHERE approval_id=?", (approval_id,))
                raise ApprovalError("approval_expired")
            payload = json.loads(row["payload_json"])
            _, digest = self._serialized(payload)
            target = f"{payload.get('kind', '')}:{payload.get('record_id', '')}"
            if digest != row["payload_digest"] or target != row["target"]:
                raise ApprovalError("approval_action_mismatch")
            db.execute("UPDATE app_approvals SET status='claimed' WHERE approval_id=?", (approval_id,))
            return {"approval_id": approval_id, "agent_id": row["agent_id"],
                    "capability": row["capability"], "payload": payload,
                    "correlation_id": row["correlation_id"]}

    def finish(self, approval_id: str, *, succeeded: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE app_approvals SET status=? WHERE approval_id=? AND status='claimed'",
                       ("completed" if succeeded else "failed", approval_id))
