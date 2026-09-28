from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping
from uuid import uuid4
from datetime import datetime, timezone

from .profile import Profile


_KINDS = frozenset({
    "task", "calendar", "goal", "project", "commitment", "learning", "body",
    "information", "finance", "life_admin", "creation", "interest", "experience",
})


class RecordConflict(ValueError):
    """A version or idempotency guard rejected a write."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["record_id"],
        "kind": row["kind"],
        "data": json.loads(row["payload_json"]),
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class LocalStore:
    def __init__(self, profile: Profile) -> None:
        if not isinstance(profile, Profile):
            raise TypeError("profile must be a Profile")
        self.profile = profile
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.profile.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported local database schema version")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS records_kind_idx ON records(kind, created_at);
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    record_id TEXT NOT NULL REFERENCES records(record_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
                """
            )

    @staticmethod
    def _validate(kind: str, actor: str, correlation_id: str) -> None:
        if kind not in _KINDS:
            raise ValueError("unsupported record kind")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("correlation_id is required")

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        actor: str,
        operation: str,
        record_id: str,
        correlation_id: str,
        payload_json: str,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                actor,
                operation,
                record_id,
                correlation_id,
                hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                _now(),
            ),
        )

    def create(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._validate(kind, actor, correlation_id)
        serialized = _canonical(payload)
        request_digest = hashlib.sha256(f"{kind}:{serialized}".encode("utf-8")).hexdigest()
        if idempotency_key is not None and not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                previous = connection.execute(
                    "SELECT request_digest, record_id FROM idempotency WHERE key=?",
                    (idempotency_key,),
                ).fetchone()
                if previous is not None:
                    if previous["request_digest"] != request_digest:
                        raise RecordConflict("idempotency key was used for another request")
                    row = connection.execute(
                        "SELECT * FROM records WHERE record_id=?", (previous["record_id"],)
                    ).fetchone()
                    if row is None:
                        raise RecordConflict("idempotency record is corrupt")
                    return _record(row)
            record_id = uuid4().hex
            timestamp = _now()
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, 1, ?, ?)",
                (record_id, kind, serialized, timestamp, timestamp),
            )
            if idempotency_key is not None:
                connection.execute(
                    "INSERT INTO idempotency VALUES (?, ?, ?)",
                    (idempotency_key, request_digest, record_id),
                )
            self._audit(
                connection, actor=actor, operation=f"{kind}.create", record_id=record_id,
                correlation_id=correlation_id, payload_json=serialized,
            )
            row = connection.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone()
            assert row is not None
            return _record(row)

    def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        if kind not in _KINDS:
            raise ValueError("unsupported record kind")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE kind=? AND record_id=?", (kind, record_id)
            ).fetchone()
        return _record(row) if row is not None else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        if kind not in _KINDS:
            raise ValueError("unsupported record kind")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM records WHERE kind=? ORDER BY created_at, record_id", (kind,)
            ).fetchall()
        return [_record(row) for row in rows]

    def update(
        self,
        kind: str,
        record_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        self._validate(kind, actor, correlation_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be positive")
        serialized = _canonical(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                "UPDATE records SET payload_json=?, version=version+1, updated_at=? "
                "WHERE kind=? AND record_id=? AND version=?",
                (serialized, _now(), kind, record_id, expected_version),
            )
            if result.rowcount != 1:
                raise RecordConflict("record version has changed or record is missing")
            self._audit(
                connection, actor=actor, operation=f"{kind}.update", record_id=record_id,
                correlation_id=correlation_id, payload_json=serialized,
            )
            row = connection.execute("SELECT * FROM records WHERE record_id=?", (record_id,)).fetchone()
            assert row is not None
            return _record(row)

    def backup(self, destination: str | Path) -> str:
        target = Path(destination).resolve()
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source:
            with sqlite3.connect(target) as backup_connection:
                source.backup(backup_connection)
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def restore(self, backup_path: str | Path) -> Path:
        source_path = Path(backup_path).resolve()
        if not source_path.is_file() or source_path == self.profile.database_path.resolve():
            raise ValueError("restore source must be a separate backup file")
        try:
            with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source:
                if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("backup integrity check failed")
                if source.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValueError("unsupported backup schema version")
                if source.execute("SELECT count(*) FROM records").fetchone()[0] < 0:
                    raise ValueError("backup records are invalid")
        except sqlite3.DatabaseError as exc:
            raise ValueError("backup database is invalid") from exc
        rescue = self.profile.root / "recovery" / f"pre-restore-{uuid4().hex}.sqlite3"
        self.backup(rescue)
        with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source:
            with self._connect() as destination:
                source.backup(destination)
        return rescue
