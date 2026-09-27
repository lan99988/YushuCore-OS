"""认知资产库（SQLite）。

物理落点：与信息层同一个 `04_数据中心（Data）/数据库/information_objects.db`
（单库多表，与 ADR-008「本地 SQLite 承载结构化属性/状态机」一致）。

职责边界：**只负责持久化与幂等**。派发、重试、冲突判定在 persistence.py。

依赖：仅标准库。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .models import (
    COGNITIVE_TYPES,
    BilingualTag,
    CognitiveAsset,
    Relation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_RELATIVE = Path("04_数据中心（Data）") / "数据库" / "information_objects.db"

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS cognitive_asset (
        cognitive_id TEXT PRIMARY KEY,
        cognitive_type TEXT NOT NULL,
        title TEXT NOT NULL,
        statement TEXT NOT NULL DEFAULT '',
        tags_json TEXT NOT NULL DEFAULT '[]',
        source_object_id TEXT NOT NULL DEFAULT '',
        relations_json TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.0,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        cognitive_status TEXT NOT NULL DEFAULT 'active',
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL DEFAULT '',
        ima_status TEXT NOT NULL DEFAULT 'pending',
        ima_ref TEXT NOT NULL DEFAULT '',
        feishu_status TEXT NOT NULL DEFAULT 'pending',
        feishu_ref TEXT NOT NULL DEFAULT '',
        sync_state TEXT NOT NULL DEFAULT 'PENDING',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cognitive_type ON cognitive_asset(cognitive_type)",
    "CREATE INDEX IF NOT EXISTS idx_cognitive_sync ON cognitive_asset(sync_state)",
    "CREATE INDEX IF NOT EXISTS idx_cognitive_source_object ON cognitive_asset(source_object_id)",
    """
    CREATE TABLE IF NOT EXISTS cognitive_tag_registry (
        zh TEXT PRIMARY KEY,
        en TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'confirmed',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cognitive_retry_queue (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cognitive_id TEXT NOT NULL,
        target TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (cognitive_id, target)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cognitive_sync_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cognitive_id TEXT NOT NULL,
        target TEXT NOT NULL,
        action TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_sync_state(ima_status: str, feishu_status: str, *, ima_hash: str = "", feishu_hash: str = "", local_hash: str = "") -> str:
    """由两库持久化状态推导汇总状态（计划书第二十四节）。

    内容冲突优先：两库均 synced 但内容哈希与本地不一致 → CONTENT_CONFLICT。
    """
    if "conflict" in (ima_status, feishu_status):
        return "CONTENT_CONFLICT"
    if ima_status == "synced" and feishu_status == "synced":
        if local_hash and ((ima_hash and ima_hash != local_hash) or (feishu_hash and feishu_hash != local_hash)):
            return "CONTENT_CONFLICT"
        return "SYNCED"
    if ima_status == "synced" and feishu_status in ("pending", "failed"):
        return "IMA_ONLY"
    if feishu_status == "synced" and ima_status in ("pending", "failed"):
        return "FEISHU_ONLY"
    if "failed" in (ima_status, feishu_status):
        return "SYNC_FAILED"
    return "PENDING"


class CognitiveStore:
    """认知资产持久化。线程安全性与信息层一致（单写者假设 + 短事务）。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = PROJECT_ROOT / DEFAULT_DB_RELATIVE
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        for statement in _DDL:
            self._conn.execute(statement)
        self._conn.commit()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        yield self._conn
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- 序号

    def next_sequence(self, prefix: str, date_key: str) -> int:
        """取 (prefix, date) 下一个可用序号。保证 allocate 幂等无碰撞。"""
        like = f"{prefix}-{date_key}-%"
        with self._tx() as conn:
            row = conn.execute(
                "SELECT cognitive_id FROM cognitive_asset WHERE cognitive_id LIKE ? ORDER BY cognitive_id DESC LIMIT 1",
                (like,),
            ).fetchone()
        if row is None:
            return 1
        tail = str(row["cognitive_id"]).rsplit("-", 1)[-1]
        try:
            return int(tail) + 1
        except ValueError:
            return 1

    # ---------------------------------------------------------------- 资产

    def save_asset(self, asset: CognitiveAsset) -> CognitiveAsset:
        now = utc_now_iso()
        created = asset.created_at or now
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO cognitive_asset (
                    cognitive_id, cognitive_type, title, statement, tags_json,
                    source_object_id, relations_json, confidence, evidence_json,
                    cognitive_status, version, content_hash,
                    ima_status, ima_ref, feishu_status, feishu_ref, sync_state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cognitive_id) DO UPDATE SET
                    title=excluded.title,
                    statement=excluded.statement,
                    tags_json=excluded.tags_json,
                    relations_json=excluded.relations_json,
                    confidence=excluded.confidence,
                    evidence_json=excluded.evidence_json,
                    cognitive_status=excluded.cognitive_status,
                    version=excluded.version,
                    content_hash=excluded.content_hash,
                    ima_status=excluded.ima_status,
                    ima_ref=excluded.ima_ref,
                    feishu_status=excluded.feishu_status,
                    feishu_ref=excluded.feishu_ref,
                    sync_state=excluded.sync_state,
                    updated_at=excluded.updated_at
                """,
                (
                    asset.cognitive_id,
                    asset.cognitive_type,
                    asset.title,
                    asset.statement,
                    json.dumps([tag.to_dict() for tag in asset.tags], ensure_ascii=False),
                    asset.source_object_id,
                    json.dumps([relation.to_dict() for relation in asset.relations], ensure_ascii=False),
                    asset.confidence,
                    json.dumps(list(asset.evidence), ensure_ascii=False),
                    asset.cognitive_status,
                    asset.version,
                    asset.content_hash,
                    asset.ima_status,
                    asset.ima_ref,
                    asset.feishu_status,
                    asset.feishu_ref,
                    asset.sync_state,
                    created,
                    now,
                ),
            )
        return asset.with_updates(created_at=created, updated_at=now)

    def get_asset(self, cognitive_id: str) -> CognitiveAsset | None:
        row = self._conn.execute(
            "SELECT * FROM cognitive_asset WHERE cognitive_id = ?", (cognitive_id,)
        ).fetchone()
        return self._row_to_asset(row) if row else None

    def find_by_source_object(self, object_id: str, cognitive_type: str | None = None) -> list[CognitiveAsset]:
        sql = "SELECT * FROM cognitive_asset WHERE source_object_id = ?"
        params: list[Any] = [object_id]
        if cognitive_type:
            sql += " AND cognitive_type = ?"
            params.append(cognitive_type)
        return [self._row_to_asset(row) for row in self._conn.execute(sql, params)]

    def list_assets(self, *, cognitive_type: str | None = None, sync_state: str | None = None, limit: int = 200) -> list[CognitiveAsset]:
        sql = "SELECT * FROM cognitive_asset WHERE 1=1"
        params: list[Any] = []
        if cognitive_type:
            _require_type(cognitive_type)
            sql += " AND cognitive_type = ?"
            params.append(cognitive_type)
        if sync_state:
            sql += " AND sync_state = ?"
            params.append(sync_state)
        sql += " ORDER BY created_at DESC, cognitive_id DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_asset(row) for row in self._conn.execute(sql, params)]

    def search_assets(self, query: str, *, limit: int = 20) -> list[CognitiveAsset]:
        """本地检索（LIKE 足够一期使用；语义检索属后续 Cognitive Retrieval 演进）。"""
        needle = f"%{query.strip()}%"
        rows = self._conn.execute(
            """
            SELECT * FROM cognitive_asset
            WHERE title LIKE ? OR statement LIKE ? OR tags_json LIKE ?
            ORDER BY confidence DESC, updated_at DESC LIMIT ?
            """,
            (needle, needle, needle, limit),
        ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def update_persistence(
        self,
        cognitive_id: str,
        *,
        target: str,
        status: str,
        ref: str | None = None,
        remote_hash: str = "",
    ) -> CognitiveAsset:
        """更新单库持久化状态并重算 sync_state（不允许直接改认知字段）。"""
        if target not in ("ima", "feishu"):
            raise ValueError(f"非法持久化目标: {target}")
        asset = self.get_asset(cognitive_id)
        if asset is None:
            raise KeyError(f"认知资产不存在: {cognitive_id}")
        if status not in ("pending", "synced", "failed", "conflict"):
            raise ValueError(f"非法持久化状态: {status}")
        changes: dict[str, Any] = {}
        if target == "ima":
            changes["ima_status"] = status
            if ref is not None:
                changes["ima_ref"] = ref
        else:
            changes["feishu_status"] = status
            if ref is not None:
                changes["feishu_ref"] = ref
        updated = asset.with_updates(**changes)
        local_hash = updated.content_hash
        ima_hash = remote_hash if target == "ima" else ""
        feishu_hash = remote_hash if target == "feishu" else ""
        updated = updated.with_updates(
            sync_state=compute_sync_state(
                updated.ima_status, updated.feishu_status,
                ima_hash=ima_hash, feishu_hash=feishu_hash, local_hash=local_hash,
            )
        )
        return self.save_asset(updated)

    # ---------------------------------------------------------------- 重试队列

    def enqueue_retry(self, cognitive_id: str, target: str, error: str) -> None:
        now = utc_now_iso()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO cognitive_retry_queue (cognitive_id, target, attempts, last_error, status, created_at, updated_at)
                VALUES (?, ?, 1, ?, 'open', ?, ?)
                ON CONFLICT(cognitive_id, target) DO UPDATE SET
                    attempts = cognitive_retry_queue.attempts + 1,
                    last_error = excluded.last_error,
                    status = 'open',
                    updated_at = excluded.updated_at
                """,
                (cognitive_id, target, error[:500], now, now),
            )

    def open_retries(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM cognitive_retry_queue WHERE status = 'open' ORDER BY updated_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_retry(self, cognitive_id: str, target: str, *, status: str) -> None:
        if status not in ("open", "done", "dead"):
            raise ValueError(f"非法重试状态: {status}")
        with self._tx() as conn:
            conn.execute(
                "UPDATE cognitive_retry_queue SET status = ?, updated_at = ? WHERE cognitive_id = ? AND target = ?",
                (status, utc_now_iso(), cognitive_id, target),
            )

    # ---------------------------------------------------------------- 标签注册表

    def upsert_tag(self, zh: str, en: str, status: str) -> None:
        now = utc_now_iso()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO cognitive_tag_registry (zh, en, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(zh) DO UPDATE SET en = excluded.en, status = excluded.status, updated_at = excluded.updated_at
                """,
                (zh, en, status, now, now),
            )

    def load_tags(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT zh, en FROM cognitive_tag_registry WHERE status = 'confirmed' AND en != ''"
        ).fetchall()
        return {str(row["zh"]): str(row["en"]) for row in rows}

    def list_tag_candidates(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT zh, en, status, updated_at FROM cognitive_tag_registry WHERE status != 'confirmed' ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- 同步日志

    def append_sync_log(self, cognitive_id: str, target: str, action: str, detail: dict[str, Any] | None = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO cognitive_sync_log (cognitive_id, target, action, detail_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (cognitive_id, target, action, json.dumps(detail or {}, ensure_ascii=False), utc_now_iso()),
            )

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> CognitiveAsset:
        tags = tuple(
            BilingualTag.from_dict(item)
            for item in json.loads(row["tags_json"] or "[]")
        )
        relations = tuple(
            Relation.from_dict(item)
            for item in json.loads(row["relations_json"] or "[]")
        )
        return CognitiveAsset(
            cognitive_id=str(row["cognitive_id"]),
            cognitive_type=str(row["cognitive_type"]),
            title=str(row["title"]),
            statement=str(row["statement"]),
            tags=tags,
            source_object_id=str(row["source_object_id"]),
            relations=relations,
            confidence=float(row["confidence"]),
            evidence=tuple(json.loads(row["evidence_json"] or "[]")),
            cognitive_status=str(row["cognitive_status"]),
            version=int(row["version"]),
            ima_status=str(row["ima_status"]),
            ima_ref=str(row["ima_ref"]),
            feishu_status=str(row["feishu_status"]),
            feishu_ref=str(row["feishu_ref"]),
            sync_state=str(row["sync_state"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _require_type(cognitive_type: str) -> None:
    if cognitive_type not in COGNITIVE_TYPES:
        raise ValueError(f"非法认知类型: {cognitive_type}")
