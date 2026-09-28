"""Explicit, read-only legacy previews and repeatable business-data import."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from uuid import uuid4

from .store import LocalStore


class LegacyMigrator:
    def __init__(self, store: LocalStore) -> None:
        self.store = store

    @staticmethod
    def _legacy_rows(source: str | Path) -> list[dict[str, str]]:
        path = Path(source).resolve()
        if not path.is_file():
            raise ValueError("legacy information database is missing")
        try:
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute("SELECT object_id, source_key, title, excerpt, source "
                                  "FROM information_object ORDER BY object_id").fetchall()
        except sqlite3.DatabaseError as exc:
            raise ValueError("legacy information database has an unsupported schema") from exc
        result = [dict(row) for row in rows]
        if any(not row["object_id"] or not row["source_key"] or not row["title"] for row in result):
            raise ValueError("legacy information database contains invalid objects")
        return result

    def preview_information(self, source: str | Path) -> dict:
        rows = self._legacy_rows(source)
        return {"source": "legacy_information_sqlite", "count": len(rows),
                "items": [{"object_id": row["object_id"], "title": row["title"]} for row in rows],
                "writes": False}

    def import_information(self, source: str | Path) -> dict:
        rows = self._legacy_rows(source)
        backup = self.store.profile.root / "migration_backups" / f"pre-import-{uuid4().hex}.sqlite3"
        self.store.backup(backup)
        existing = {record["id"] for record in self.store.list("information")}
        imported = 0
        for row in rows:
            record = self.store.create("information", {
                "title": row["title"], "summary": row["excerpt"], "source": row["source"],
                "legacy_object_id": row["object_id"], "legacy_source_key": row["source_key"],
            }, actor="migration", correlation_id=f"migration-{row['object_id']}",
                idempotency_key=f"legacy-information:{row['source_key']}")
            if record["id"] not in existing:
                imported += 1
                existing.add(record["id"])
        return {"source": "legacy_information_sqlite", "scanned": len(rows),
                "imported": imported, "pre_import_backup": str(backup)}

    def preview_knowledge(self, root: str | Path) -> dict:
        archive = Path(root).resolve()
        if not archive.is_dir():
            raise ValueError("legacy knowledge archive is missing")
        paths = sorted(path.relative_to(archive).as_posix() for path in archive.rglob("*.md")
                       if path.is_file() and not path.is_symlink()
                       and path.resolve().is_relative_to(archive))
        return {"source": "legacy_knowledge_archive", "count": len(paths),
                "paths": paths, "writes": False, "upload_to_ima": False}
