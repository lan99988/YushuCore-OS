from __future__ import annotations

from pathlib import Path

import pytest


def test_vault_layout_initialization_is_explicit_and_markdown_first(tmp_path: Path):
    from knowledge_system.vault import VaultLayout

    layout = VaultLayout(tmp_path / "vault")
    with pytest.raises(PermissionError, match="approval"):
        layout.initialize(approved=False)
    created = layout.initialize(approved=True)

    assert (tmp_path / "vault/00_Inbox").is_dir()
    assert (tmp_path / "vault/99_System").is_dir()
    assert len(created) == 15


def test_markdown_index_builds_searchable_metadata_without_replacing_source(tmp_path: Path):
    from knowledge_system.index import MarkdownIndex

    (tmp_path / "note.md").write_text(
        "---\nid: KN-1\ntype: knowledge\ndomain: study\nstatus: validated\n---\n# Python Study\n\nPractice daily.\n",
        encoding="utf-8",
    )
    index = MarkdownIndex(tmp_path / "index.json")
    assert index.build() == 1
    assert index.search("python")[0]["id"] == "KN-1"
    assert "# Python Study" in (tmp_path / "note.md").read_text(encoding="utf-8")


def test_backup_restore_requires_explicit_approval(tmp_path: Path):
    from knowledge_system.backup import VaultBackup

    source = tmp_path / "vault"
    source.mkdir()
    (source / "note.md").write_text("original", encoding="utf-8")
    backup = VaultBackup(tmp_path / "backups")
    archive = backup.create(source)
    (source / "note.md").write_text("changed", encoding="utf-8")

    with pytest.raises(PermissionError, match="approval"):
        backup.restore(archive, source, approved=False)
    backup.restore(archive, source, approved=True)
    assert (source / "note.md").read_text(encoding="utf-8") == "original"


def test_migration_guard_blocks_automatic_asset_migration():
    from knowledge_system.migration import MigrationGuard

    with pytest.raises(PermissionError, match="Human"):
        MigrationGuard().require_approved(False)
    assert MigrationGuard().require_approved(True) is True
