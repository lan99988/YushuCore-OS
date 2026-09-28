from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from yushu_app.cli import main


def _call(capsys, *args: str) -> dict:
    assert main(["--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_init_capture_and_today_share_persistent_profile(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    initialized = _call(capsys, *base, "init")
    assert initialized["status"] == "completed"

    captured = _call(capsys, *base, "run", "capture", "写周报", "--kind", "task")
    assert captured["status"] == "completed"
    today = _call(capsys, *base, "run", "today", "今天做什么")
    assert today["data"]["tasks"][0]["data"]["title"] == "写周报"


def test_cli_capability_json_and_health_without_ima(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    _call(capsys, *base, "init")
    catalog = _call(capsys, *base, "capabilities")
    assert any(item["name"] == "knowledge.search" for item in catalog["data"])
    health = _call(capsys, *base, "health")
    assert health["knowledge"]["status"] == "not_configured"


def test_cli_owner_approval_is_explicit_and_persistent(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    _call(capsys, *base, "init")
    pending = _call(capsys, *base, "invoke", "local_record.create",
                    '{"kind":"commitment","data":{"title":"发资料"},"affects_commitment":true}',
                    "--agent", "agent-a")
    assert pending["status"] == "pending_approval"
    listed = _call(capsys, *base, "approvals")
    assert listed["data"][0]["approval_id"] == pending["approval_id"]
    approved = _call(capsys, *base, "approve", pending["approval_id"], "--confirm")
    assert approved["status"] == "completed"


def test_cli_backup_and_confirmed_restore(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    _call(capsys, *base, "init")
    _call(capsys, *base, "run", "capture", "A", "--kind", "task")
    backup = tmp_path / "backup.sqlite3"
    assert _call(capsys, *base, "backup", str(backup))["status"] == "completed"
    _call(capsys, *base, "run", "capture", "B", "--kind", "task")
    restored = _call(capsys, *base, "restore", str(backup), "--confirm")
    assert restored["status"] == "completed"
    assert Path(restored["pre_restore_backup"]).is_file()
    today = _call(capsys, *base, "run", "today", "today")
    assert len(today["data"]["tasks"]) == 1


def test_cli_legacy_migration_requires_preview_and_explicit_execution(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    _call(capsys, *base, "init")
    legacy = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy) as db:
        db.execute("CREATE TABLE information_object (object_id TEXT, source_key TEXT, title TEXT, excerpt TEXT, source TEXT)")
        db.execute("INSERT INTO information_object VALUES ('1','key','旧信息','摘要','old')")
    preview = _call(capsys, *base, "migrate-preview", "information", str(legacy))
    assert preview["data"]["count"] == 1
    imported = _call(capsys, *base, "migrate-execute", "information", str(legacy), "--confirm")
    assert imported["data"]["imported"] == 1


def test_cli_diagnostics_is_read_only_and_does_not_claim_online_without_probe(tmp_path: Path, capsys):
    base = ("--home", str(tmp_path), "--profile", "test")
    _call(capsys, *base, "init")
    report = _call(capsys, *base, "diagnose")
    assert report["status"] == "completed"
    assert report["data"]["ima"]["status"] == "not_configured"
    assert report["data"]["ollama"]["status"] == "configured_unverified"
