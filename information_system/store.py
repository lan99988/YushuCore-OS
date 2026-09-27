"""信息对象库（SQLite）。

物理落点：`04_数据中心（Data）/数据库/information_objects.db`

职责边界：**只负责持久化与幂等**。领域观察区的判定策略在 `observation.py`，
识别逻辑在 `recognition.py`。本模块不做任何推断。

依赖：仅标准库（sqlite3 / json / hashlib / datetime / pathlib）。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .models import (
    DomainCandidate,
    DomainRecord,
    InformationObject,
    LayerVerdict,
    RecognitionReport,
    Relation,
    ScoredItem,
    TopicObservation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_RELATIVE = Path("04_数据中心（Data）") / "数据库" / "information_objects.db"

SCHEMA_VERSION = 1

_OBJECT_COLUMNS = (
    "object_id",
    "source_key",
    "source",
    "source_ref",
    "source_container",
    "title",
    "excerpt",
    "content_digest",
    "temporal",
    "deadline",
    "types_json",
    "knowledge_level",
    "cognitive_os_detected",
    "cognitive_os_level",
    "domains_json",
    "domain_candidates_json",
    "unknown_topic",
    "concepts_json",
    "relations_json",
    "projects_json",
    "actions_json",
    "attributes_json",
    "confidence",
    "evidence_json",
    "reason",
    "status",
    "decision_state",
    "reviewer",
    "review_time",
    "correlation_id",
    "created_at",
    "updated_at",
)

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS information_object (
        object_id TEXT PRIMARY KEY,
        source_key TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL,
        source_ref TEXT NOT NULL DEFAULT '',
        source_container TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        excerpt TEXT NOT NULL DEFAULT '',
        content_digest TEXT NOT NULL DEFAULT '',
        temporal TEXT NOT NULL DEFAULT 'no_requirement',
        deadline TEXT,
        types_json TEXT NOT NULL DEFAULT '[]',
        knowledge_level TEXT NOT NULL DEFAULT 'information',
        cognitive_os_detected INTEGER NOT NULL DEFAULT 0,
        cognitive_os_level TEXT NOT NULL DEFAULT 'none',
        domains_json TEXT NOT NULL DEFAULT '[]',
        domain_candidates_json TEXT NOT NULL DEFAULT '[]',
        unknown_topic INTEGER NOT NULL DEFAULT 0,
        concepts_json TEXT NOT NULL DEFAULT '[]',
        relations_json TEXT NOT NULL DEFAULT '[]',
        projects_json TEXT NOT NULL DEFAULT '[]',
        actions_json TEXT NOT NULL DEFAULT '[]',
        attributes_json TEXT NOT NULL DEFAULT '{}',
        confidence REAL NOT NULL DEFAULT 0.0,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'captured',
        decision_state TEXT NOT NULL DEFAULT 'detected',
        reviewer TEXT NOT NULL DEFAULT '',
        review_time TEXT,
        correlation_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_object_source ON information_object(source)",
    "CREATE INDEX IF NOT EXISTS idx_object_status ON information_object(status)",
    "CREATE INDEX IF NOT EXISTS idx_object_decision ON information_object(decision_state)",
    """
    CREATE TABLE IF NOT EXISTS information_event (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        actor TEXT NOT NULL DEFAULT 'system',
        correlation_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (object_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_object ON information_event(object_id, seq)",
    """
    CREATE TABLE IF NOT EXISTS recognition_report (
        report_id TEXT PRIMARY KEY,
        object_id TEXT NOT NULL,
        backend TEXT NOT NULL,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_report_object ON recognition_report(object_id)",
    """
    CREATE TABLE IF NOT EXISTS domain_registry (
        domain_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        slug TEXT NOT NULL DEFAULT '',
        parent_id TEXT,
        state TEXT NOT NULL DEFAULT 'observation',
        description TEXT NOT NULL DEFAULT '',
        evidence_count INTEGER NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0.0,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        reason TEXT NOT NULL DEFAULT '',
        merged_into TEXT,
        promoted_from TEXT,
        confirmed_by TEXT NOT NULL DEFAULT '',
        confirmed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_domain_state ON domain_registry(state)",
    """
    CREATE TABLE IF NOT EXISTS topic_observation (
        topic_id TEXT PRIMARY KEY,
        label TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL DEFAULT 'observation',
        object_ids_json TEXT NOT NULL DEFAULT '[]',
        layers_json TEXT NOT NULL DEFAULT '[]',
        growth_json TEXT NOT NULL DEFAULT '{}',
        confidence REAL NOT NULL DEFAULT 0.0,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS object_domain (
        object_id TEXT NOT NULL,
        domain_id TEXT NOT NULL,
        domain_name TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        is_candidate INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (object_id, domain_id, is_candidate)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_object_domain ON object_domain(domain_name, is_candidate)",
    """
    CREATE TABLE IF NOT EXISTS relation (
        relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_object_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        target_object_id TEXT,
        target_label TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.0,
        UNIQUE (from_object_id, relation_type, target_label)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_relation_from ON relation(from_object_id)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


def _load(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class InformationStore:
    """信息对象库。幂等写入：同一 `source_key` 重复 upsert 不产生新对象。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else PROJECT_ROOT / DEFAULT_DB_RELATIVE

    # ---------------------------------------------------------------- 连接

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn, conn:
            for statement in _DDL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )

    # ------------------------------------------------------------ 信息对象

    def upsert_object(self, obj: InformationObject, *, actor: str = "system") -> tuple[str, bool]:
        """写入或更新信息对象，返回 (object_id, created)。"""
        now = _now()
        source_key = obj.source_key
        with self.connect() as conn, conn:
            row = conn.execute(
                "SELECT object_id, created_at FROM information_object WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if row is None:
                object_id = obj.resolved_object_id
                created_at = now
                created = True
                event_type = "captured"
            else:
                object_id = row["object_id"]
                created_at = row["created_at"]
                created = False
                event_type = "updated"

            payload = self._object_row(obj, object_id, source_key, created_at, now)
            columns = ", ".join(_OBJECT_COLUMNS)
            placeholders = ", ".join(f":{name}" for name in _OBJECT_COLUMNS)
            conn.execute(
                f"INSERT OR REPLACE INTO information_object ({columns}) VALUES ({placeholders})",
                payload,
            )
            self._sync_domains(conn, object_id, obj)
            self._sync_relations(conn, object_id, obj)
            self._append_event(
                conn,
                object_id,
                event_type,
                {
                    "source": obj.source,
                    "title": obj.title,
                    "status": obj.status,
                    "decision_state": obj.decision_state,
                },
                actor,
                obj.correlation_id,
            )
        return object_id, created

    @staticmethod
    def _object_row(
        obj: InformationObject,
        object_id: str,
        source_key: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        return {
            "object_id": object_id,
            "source_key": source_key,
            "source": obj.source,
            "source_ref": obj.source_ref,
            "source_container": obj.source_container,
            "title": obj.title,
            "excerpt": obj.excerpt,
            "content_digest": obj.content_digest,
            "temporal": obj.temporal,
            "deadline": obj.deadline,
            "types_json": _dump(list(obj.types)),
            "knowledge_level": obj.knowledge_level,
            "cognitive_os_detected": int(obj.cognitive_os_detected),
            "cognitive_os_level": obj.cognitive_os_level,
            "domains_json": _dump(list(obj.domains)),
            "domain_candidates_json": _dump([item.to_dict() for item in obj.domain_candidates]),
            "unknown_topic": int(obj.unknown_topic),
            "concepts_json": _dump([item.to_dict() for item in obj.concepts]),
            "relations_json": _dump([item.to_dict() for item in obj.relations]),
            "projects_json": _dump([item.to_dict() for item in obj.projects]),
            "actions_json": _dump([item.to_dict() for item in obj.actions]),
            "attributes_json": _dump(obj.attributes),
            "confidence": float(obj.confidence),
            "evidence_json": _dump(list(obj.evidence)),
            "reason": obj.reason,
            "status": obj.status,
            "decision_state": obj.decision_state,
            "reviewer": obj.reviewer,
            "review_time": obj.review_time,
            "correlation_id": obj.correlation_id,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    @staticmethod
    def _sync_domains(conn: sqlite3.Connection, object_id: str, obj: InformationObject) -> None:
        conn.execute("DELETE FROM object_domain WHERE object_id = ?", (object_id,))
        rows: list[tuple[str, str, str, float, int]] = []
        for name in obj.domains:
            rows.append((object_id, _domain_id(name), name, 1.0, 0))
        for candidate in obj.domain_candidates:
            rows.append((object_id, _domain_id(candidate.name), candidate.name, candidate.confidence, 1))
        # 按 (domain_id, is_candidate) 去重，与主键一致，避免同域重复导致 PK 冲突
        deduped = {(row[1], row[4]): row for row in rows}
        conn.executemany(
            "INSERT OR REPLACE INTO object_domain"
            " (object_id, domain_id, domain_name, confidence, is_candidate) VALUES (?, ?, ?, ?, ?)",
            list(deduped.values()),
        )

    @staticmethod
    def _sync_relations(conn: sqlite3.Connection, object_id: str, obj: InformationObject) -> None:
        conn.execute("DELETE FROM relation WHERE from_object_id = ?", (object_id,))
        rows = [
            (
                object_id,
                item.relation_type,
                item.target_object_id or None,
                item.target_label,
                item.confidence,
            )
            for item in obj.relations
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO relation"
            " (from_object_id, relation_type, target_object_id, target_label, confidence)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        object_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        correlation_id: str = "",
    ) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM information_event WHERE object_id = ?",
            (object_id,),
        ).fetchone()
        seq = int(row[0])
        conn.execute(
            "INSERT INTO information_event"
            " (object_id, seq, event_type, payload_json, actor, correlation_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (object_id, seq, event_type, _dump(payload), actor, correlation_id, _now()),
        )
        return seq

    def record_event(
        self, object_id: str, event_type: str, payload: dict[str, Any] | None = None, *, actor: str = "system"
    ) -> int:
        """追加一条事件。append-only，不修改历史行——对应 IMA 的 append 语义。"""
        with self.connect() as conn, conn:
            return self._append_event(conn, object_id, event_type, payload or {}, actor)

    def get(self, object_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM information_object WHERE object_id = ?", (object_id,)
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def find_by_source_key(self, source_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM information_object WHERE source_key = ?", (source_key,)
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def find_by_content_digest(
        self, digest: str, *, exclude_object_id: str = ""
    ) -> list[dict[str, Any]]:
        """按正文指纹查同内容对象。**只读**：仅用于「同内容不同来源」参考，
        不返回合并/删除能力（原始来源不得因重复被丢弃）。"""
        if not digest:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM information_object WHERE content_digest = ? AND object_id != ?"
                " ORDER BY created_at ASC",
                (digest, exclude_object_id),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_objects(
        self,
        *,
        status: str | None = None,
        decision_state: str | None = None,
        source: str | None = None,
        domain: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("o.status = ?")
            params.append(status)
        if decision_state is not None:
            clauses.append("o.decision_state = ?")
            params.append(decision_state)
        if source is not None:
            clauses.append("o.source = ?")
            params.append(source)
        if domain is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM object_domain d WHERE d.object_id = o.object_id AND d.domain_name = ?)"
            )
            params.append(domain)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT o.* FROM information_object o{where} ORDER BY o.updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def history(self, object_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, payload_json, actor, correlation_id, created_at"
                " FROM information_event WHERE object_id = ? ORDER BY seq ASC",
                (object_id,),
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "event_type": row["event_type"],
                "payload": _load(row["payload_json"], {}),
                "actor": row["actor"],
                "correlation_id": row["correlation_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def set_lifecycle(self, object_id: str, status: str, *, actor: str = "system") -> str:
        """流转生命周期。非法迁移抛 ValueError，不做静默纠正。"""
        current = self._require_object(object_id)
        updated = _hydrate_object(current).with_lifecycle(status)
        now = _now()
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE information_object SET status = ?, updated_at = ? WHERE object_id = ?",
                (updated.status, now, object_id),
            )
            self._append_event(
                conn, object_id, "lifecycle", {"from": current["status"], "to": updated.status}, actor
            )
        return updated.status

    def confirm_object(self, object_id: str, *, reviewer: str, actor: str | None = None) -> str:
        """人工确认。**这是唯一能写入 confirmed 的入口**，必须有 reviewer。"""
        current = self._require_object(object_id)
        updated = _hydrate_object(current).confirmed(reviewer=reviewer, review_time=_now())
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE information_object SET decision_state = ?, reviewer = ?, review_time = ?, updated_at = ?"
                " WHERE object_id = ?",
                ("confirmed", updated.reviewer, updated.review_time, _now(), object_id),
            )
            self._append_event(conn, object_id, "confirmed", {"reviewer": reviewer}, actor or reviewer)
        return "confirmed"

    def reject_object(self, object_id: str, *, reviewer: str, reason: str) -> str:
        if not reason.strip():
            raise ValueError("rejection reason is required")
        self._require_object(object_id)
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE information_object SET decision_state = ?, reviewer = ?, review_time = ?, updated_at = ?"
                " WHERE object_id = ?",
                ("rejected", reviewer, _now(), _now(), object_id),
            )
            self._append_event(conn, object_id, "rejected", {"reviewer": reviewer, "reason": reason}, reviewer)
        return "rejected"

    def tombstone(self, object_id: str, *, reason: str, actor: str = "system") -> None:
        """墓碑：本地标记归档 + 追加事件。**不删除任何行，也不回删来源内容。**"""
        if not reason.strip():
            raise ValueError("tombstone reason is required")
        self._require_object(object_id)
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE information_object SET status = ?, updated_at = ? WHERE object_id = ?",
                ("archived", _now(), object_id),
            )
            self._append_event(conn, object_id, "tombstoned", {"reason": reason}, actor)

    def _require_object(self, object_id: str) -> dict[str, Any]:
        row = self.get(object_id)
        if row is None:
            raise ValueError(f"unknown object_id: {object_id}")
        return row

    def count(self, *, source: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM information_object"
        params: list[Any] = []
        if source is not None:
            sql += " WHERE source = ?"
            params.append(source)
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    # ------------------------------------------------------- 识别报告

    def record_report(self, report: RecognitionReport) -> str:
        report_id = f"RPT-{report.object_id}-{_now()}"
        with self.connect() as conn, conn:
            conn.execute(
                "INSERT INTO recognition_report (report_id, object_id, backend, report_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (report_id, report.object_id, report.backend, _dump(report.to_dict()), _now()),
            )
        return report_id

    def latest_report(self, object_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM recognition_report WHERE object_id = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (object_id,),
            ).fetchone()
        return _load(row["report_json"], None) if row is not None else None

    # ------------------------------------------------------- 领域注册表

    def upsert_domain(self, record: DomainRecord, *, actor: str = "system") -> str:
        now = _now()
        domain_id = record.resolved_domain_id
        with self.connect() as conn, conn:
            existing = conn.execute(
                "SELECT created_at, state FROM domain_registry WHERE name = ?", (record.name,)
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            if existing is not None and existing["state"] != record.state:
                from_state = existing["state"]
                _assert_domain_transition(from_state, record.state)
                self._append_event(
                    conn, domain_id, "domain_transition", {"from": from_state, "to": record.state}, actor
                )
            conn.execute(
                "INSERT OR REPLACE INTO domain_registry"
                " (domain_id, name, slug, parent_id, state, description, evidence_count, confidence,"
                "  evidence_json, reason, merged_into, promoted_from, confirmed_by, confirmed_at,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    domain_id,
                    record.name,
                    record.slug,
                    record.parent_id,
                    record.state,
                    record.description,
                    int(record.evidence_count),
                    float(record.confidence),
                    _dump(list(record.evidence)),
                    record.reason,
                    record.merged_into,
                    record.promoted_from,
                    record.confirmed_by,
                    record.confirmed_at,
                    created_at,
                    now,
                ),
            )
        return domain_id

    def get_domain(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM domain_registry WHERE name = ?", (name,)).fetchone()
        return dict(row) if row is not None else None

    def list_domains(self, *, state: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM domain_registry"
        params: list[Any] = []
        if state is not None:
            sql += " WHERE state = ?"
            params.append(state)
        sql += " ORDER BY state ASC, name ASC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def transition_domain(self, name: str, state: str, *, actor: str = "") -> str:
        current = self.get_domain(name)
        if current is None:
            raise ValueError(f"unknown domain: {name}")
        record = _hydrate_domain(current)
        updated = record.transition(state, actor=actor, at=_now())
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE domain_registry SET state = ?, confirmed_by = ?, confirmed_at = ?, updated_at = ?"
                " WHERE name = ?",
                (updated.state, updated.confirmed_by, updated.confirmed_at, _now(), name),
            )
            self._append_event(
                conn,
                updated.resolved_domain_id,
                "domain_transition",
                {"from": current["state"], "to": updated.state, "actor": actor},
                actor or "system",
            )
        return updated.state

    def rename_domain(self, old_name: str, new_name: str, *, actor: str = "system") -> str:
        if not new_name.strip():
            raise ValueError("new domain name is required")
        if self.get_domain(new_name) is not None:
            raise ValueError(f"domain already exists: {new_name}")
        current = self.get_domain(old_name)
        if current is None:
            raise ValueError(f"unknown domain: {old_name}")
        new_id = _domain_id(new_name)
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE domain_registry SET domain_id = ?, name = ?, updated_at = ? WHERE name = ?",
                (new_id, new_name, _now(), old_name),
            )
            conn.execute(
                "UPDATE object_domain SET domain_id = ?, domain_name = ? WHERE domain_name = ?",
                (new_id, new_name, old_name),
            )
            self._append_event(
                conn,
                new_id,
                "domain_renamed",
                {"from": old_name, "to": new_name},
                actor,
            )
        return new_name

    def merge_domains(self, source_name: str, target_name: str, *, actor: str = "system") -> str:
        if source_name == target_name:
            raise ValueError("cannot merge a domain into itself")
        target = self.get_domain(target_name)
        if target is None:
            raise ValueError(f"unknown target domain: {target_name}")
        if self.get_domain(source_name) is None:
            raise ValueError(f"unknown source domain: {source_name}")
        target_id = target["domain_id"]
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE object_domain SET domain_id = ?, domain_name = ? WHERE domain_name = ?",
                (target_id, target_name, source_name),
            )
            conn.execute(
                "UPDATE domain_registry SET state = 'merged', merged_into = ?, updated_at = ? WHERE name = ?",
                (target_id, _now(), source_name),
            )
            self._append_event(
                conn,
                _domain_id(source_name),
                "domain_merged",
                {"from": source_name, "to": target_name},
                actor,
            )
        return target_name

    def domain_object_count(self, name: str, *, confirmed_only: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM object_domain WHERE domain_name = ?"
        params: list[Any] = [name]
        if confirmed_only:
            sql += " AND is_candidate = 0"
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    # ------------------------------------------------------- 主题观察区

    def upsert_topic(self, observation: TopicObservation) -> str:
        now = _now()
        topic_id = observation.resolved_topic_id
        with self.connect() as conn, conn:
            existing = conn.execute(
                "SELECT created_at FROM topic_observation WHERE label = ?", (observation.label,)
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                "INSERT OR REPLACE INTO topic_observation"
                " (topic_id, label, state, object_ids_json, layers_json, growth_json, confidence,"
                "  reason, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    topic_id,
                    observation.label,
                    observation.state,
                    _dump(list(observation.object_ids)),
                    _dump([item.to_dict() for item in observation.layers]),
                    _dump(dict(observation.growth)),
                    float(observation.confidence),
                    observation.reason,
                    created_at,
                    now,
                ),
            )
        return topic_id

    def get_topic(self, label: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM topic_observation WHERE label = ?", (label,)).fetchone()
        return dict(row) if row is not None else None

    def list_topics(self, *, state: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM topic_observation"
        params: list[Any] = []
        if state is not None:
            sql += " WHERE state = ?"
            params.append(state)
        sql += " ORDER BY state ASC, label ASC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def transition_topic(self, label: str, state: str) -> str:
        current = self.get_topic(label)
        if current is None:
            raise ValueError(f"unknown topic: {label}")
        observation = _hydrate_topic(current)
        updated = observation.transition(state)
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE topic_observation SET state = ?, updated_at = ? WHERE label = ?",
                (updated.state, _now(), label),
            )
        return updated.state


# ------------------------------------------------------------------ 反序列化


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("types_json", "domains_json", "domain_candidates_json", "concepts_json",
                "relations_json", "projects_json", "actions_json", "attributes_json",
                "evidence_json"):
        if key in data:
            data[key.replace("_json", "")] = _load(data.pop(key), [] if key != "attributes_json" else {})
    for key in ("cognitive_os_detected", "unknown_topic"):
        if key in data:
            data[key] = bool(data[key])
    return data


def _hydrate_object(row: dict[str, Any]) -> InformationObject:
    return InformationObject(
        source=row["source"],
        title=row["title"],
        temporal=row["temporal"],
        source_ref=row["source_ref"],
        source_container=row["source_container"],
        excerpt=row["excerpt"],
        content_digest=row["content_digest"],
        deadline=row["deadline"],
        types=tuple(row["types"]),
        knowledge_level=row["knowledge_level"],
        cognitive_os_detected=bool(row["cognitive_os_detected"]),
        cognitive_os_level=row["cognitive_os_level"],
        domains=tuple(row["domains"]),
        domain_candidates=tuple(
            DomainCandidate(
                name=item["name"],
                confidence=float(item.get("confidence", 0.0)),
                evidence=tuple(item.get("evidence", ())),
                reason=item.get("reason", ""),
            )
            for item in row["domain_candidates"]
        ),
        unknown_topic=bool(row["unknown_topic"]),
        concepts=tuple(_scored(item) for item in row["concepts"]),
        relations=tuple(_relation(item) for item in row["relations"]),
        projects=tuple(_scored(item) for item in row["projects"]),
        actions=tuple(_scored(item) for item in row["actions"]),
        attributes=dict(row["attributes"]),
        confidence=float(row["confidence"]),
        evidence=tuple(row["evidence"]),
        reason=row["reason"],
        status=row["status"],
        decision_state=row["decision_state"],
        reviewer=row["reviewer"],
        review_time=row["review_time"],
        correlation_id=row["correlation_id"],
        object_id=row["object_id"],
    )


def _scored(item: dict[str, Any]) -> ScoredItem:
    return ScoredItem(
        label=item["label"],
        confidence=float(item.get("confidence", 0.0)),
        evidence=tuple(item.get("evidence", ())),
        reason=item.get("reason", ""),
        detail=dict(item.get("detail", {})),
    )


def _relation(item: dict[str, Any]) -> Relation:
    return Relation(
        relation_type=item["relation_type"],
        target_label=item["target_label"],
        target_object_id=item.get("target_object_id", ""),
        confidence=float(item.get("confidence", 0.0)),
        evidence=tuple(item.get("evidence", ())),
        reason=item.get("reason", ""),
    )


def _domain_id(name: str) -> str:
    from .models import make_domain_id

    return make_domain_id(name)


def _assert_domain_transition(from_state: str, to_state: str) -> None:
    from .models import DOMAIN_TRANSITIONS

    allowed = DOMAIN_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise ValueError(f"illegal domain transition: {from_state} -> {to_state}")


def _hydrate_domain(row: dict[str, Any]) -> DomainRecord:
    return DomainRecord(
        name=row["name"],
        state=row["state"],
        slug=row["slug"],
        parent_id=row["parent_id"],
        description=row["description"],
        evidence_count=int(row["evidence_count"]),
        confidence=float(row["confidence"]),
        evidence=tuple(_load(row["evidence_json"], [])),
        reason=row["reason"],
        merged_into=row["merged_into"],
        promoted_from=row["promoted_from"],
        confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"],
        domain_id=row["domain_id"],
    )


def _hydrate_topic(row: dict[str, Any]) -> TopicObservation:
    return TopicObservation(
        label=row["label"],
        state=row["state"],
        layers=tuple(
            LayerVerdict(
                layer=item["layer"],
                score=float(item["score"]),
                reason=item["reason"],
                evidence=tuple(item.get("evidence", ())),
            )
            for item in _load(row["layers_json"], [])
        ),
        object_ids=tuple(_load(row["object_ids_json"], [])),
        growth={k: int(v) for k, v in _load(row["growth_json"], {}).items()},
        confidence=float(row["confidence"]),
        reason=row["reason"],
        topic_id=row["topic_id"],
    )
