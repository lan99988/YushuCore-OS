from __future__ import annotations

import pytest


def test_setup_script_requires_approval_and_creates_vault(tmp_path):
    from scripts.setup_vault import setup_vault

    with pytest.raises(PermissionError):
        setup_vault(tmp_path / "vault", approved=False)
    assert len(setup_vault(tmp_path / "vault", approved=True)) == 15


def test_backup_script_delegates_to_recoverable_backup(tmp_path):
    from scripts.backup_vault import create_backup

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("x", encoding="utf-8")
    archive = create_backup(vault, tmp_path / "backups")
    assert archive.suffix == ".zip"


def test_migration_script_is_human_gated():
    from scripts.migrate_assets import approve_migration

    with pytest.raises(PermissionError):
        approve_migration(False)
    assert approve_migration(True) is True


def test_maintenance_rebuilds_markdown_index(tmp_path):
    from scripts.maintenance import rebuild_index

    (tmp_path / "note.md").write_text("---\nid: 1\n---\n# Note\n", encoding="utf-8")
    assert rebuild_index(tmp_path) == 1
    assert (tmp_path / ".system/index.json").is_file()


def test_health_check_reports_frozen_config():
    from scripts.health_check import check_config

    report = check_config("config")
    assert report["network_mode"] == "OFF"
    assert report["markdown_first"] is True
