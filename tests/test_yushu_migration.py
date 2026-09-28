from pathlib import Path
import sqlite3

from yushu_app.migration import LegacyMigrator
from yushu_app.profile import Profile
from yushu_app.store import LocalStore


def test_legacy_information_preview_backup_and_repeatable_import(tmp_path: Path):
    source = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE information_object (object_id TEXT, source_key TEXT, title TEXT, excerpt TEXT, source TEXT)")
        db.execute("INSERT INTO information_object VALUES ('old-1', 'source-1', '旧任务', '旧摘要', 'legacy')")
    profile = Profile.initialize("test", home=tmp_path)
    migrator = LegacyMigrator(LocalStore(profile))

    preview = migrator.preview_information(source)
    assert preview["count"] == 1
    assert preview["items"][0]["title"] == "旧任务"
    assert LocalStore(profile).list("information") == []

    first = migrator.import_information(source)
    second = migrator.import_information(source)
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert first["pre_import_backup"]
    assert len(LocalStore(profile).list("information")) == 1


def test_legacy_knowledge_preview_lists_paths_only(tmp_path: Path):
    root = tmp_path / "Knowledge"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "private.md").write_text("SECRET BODY", encoding="utf-8")
    migrator = LegacyMigrator(LocalStore(Profile.initialize("test", home=tmp_path)))

    preview = migrator.preview_knowledge(root)
    assert preview["count"] == 1
    assert preview["paths"] == ["notes/private.md"]
    assert "SECRET BODY" not in str(preview)
