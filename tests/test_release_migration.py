"""Isolated release migration and installation regression coverage."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
import tarfile

import pytest
import yaml

from yushuos import __version__
from yushuos.automation_store import AutomationStore
from yushuos.deployment import (
    activate_release,
    deploy,
    install_host,
    install_plugin,
    lock_plugin,
    rollback,
    uninstall_host,
    verify_release,
)
from yushuos.runtime import CoreRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = "5bf6bb5"
BASELINE_VERSION = "0.2.1"
UTC_NOW = "2026-10-05T00:00:00Z"


def _archive_baseline(destination: Path) -> Path:
    """Extract only deployable folders from the pinned 0.2.1 Git baseline."""
    archived = subprocess.run(
        ["git", "archive", "--format=tar", BASELINE, "yushuos", "yushuos_sdk", "templates"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
                raise AssertionError("pinned Git archive contains an unsafe path")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = archive.extractfile(member)
                assert payload is not None
                target.write_bytes(payload.read())
            else:
                raise AssertionError("pinned release archive must not contain links or special files")
    return destination


def _copy_current_release(destination: Path) -> Path:
    destination.mkdir(parents=True)
    for folder in ("yushuos", "yushuos_sdk", "templates"):
        shutil.copytree(
            REPO_ROOT / folder,
            destination / folder,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    return destination


def _seed_legacy_ledger(path: Path) -> tuple:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE operations (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                resource_key TEXT NOT NULL, status TEXT NOT NULL,
                receipt TEXT, updated TEXT NOT NULL
            );
            CREATE TABLE locks (resource_key TEXT PRIMARY KEY, request_id TEXT NOT NULL);
            CREATE TABLE events (
                calendar_id TEXT NOT NULL, event_id TEXT NOT NULL,
                task_guid TEXT, snapshot TEXT NOT NULL,
                PRIMARY KEY(calendar_id, event_id)
            );
            PRAGMA user_version=1;
            INSERT INTO operations VALUES (
                'legacy-success-1', 'fp-legacy-1', 'request:legacy-success-1', 'succeeded',
                '{"status":"succeeded","request_id":"legacy-success-1"}', '2024-01-02T03:04:05Z'
            );
            INSERT INTO operations VALUES (
                'legacy-unknown-1', 'fp-legacy-2', 'calendar:calendar-1', 'unknown',
                '{"status":"unknown","request_id":"legacy-unknown-1"}', '2024-01-02T03:04:06Z'
            );
            INSERT INTO locks VALUES ('calendar:calendar-1', 'legacy-unknown-1');
            INSERT INTO events VALUES (
                'calendar-1', 'calendar-event-1', 'legacy-task-1',
                '{"calendar_id":"calendar-1","event_id":"calendar-event-1","summary":"legacy"}'
            );
            """
        )
    return _legacy_ledger_snapshot(path)


def _legacy_ledger_snapshot(path: Path) -> tuple:
    with sqlite3.connect(path) as db:
        return (
            db.execute("PRAGMA user_version").fetchone()[0],
            tuple(db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY type,name"
            ).fetchall()),
            tuple(db.execute("SELECT * FROM operations ORDER BY request_id").fetchall()),
            tuple(db.execute("SELECT * FROM locks ORDER BY resource_key").fetchall()),
            tuple(db.execute("SELECT * FROM events ORDER BY calendar_id,event_id").fetchall()),
        )


def _launch_doctor(config_root: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(config_root / "bin" / "yushuos.py"), "doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def test_pinned_021_to_030_release_activation_and_rollback_preserves_ledgers(tmp_path, monkeypatch):
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("USERPROFILE", str(isolated_home))
    monkeypatch.setenv("CODEBUDDY_CONFIG_DIR", str(isolated_home / ".workbuddy"))

    baseline_source = _archive_baseline(tmp_path / "git-baseline-0.2.1")
    assert f'__version__ = "{BASELINE_VERSION}"' in (
        baseline_source / "yushuos" / "__init__.py"
    ).read_text(encoding="utf-8")

    config_root = tmp_path / "isolated-yushuos-home"
    ledger = config_root / "state" / "operations.sqlite3"
    original_ledger = _seed_legacy_ledger(ledger)
    assert deploy(baseline_source, config_root, BASELINE_VERSION)["verified"] is True
    assert _launch_doctor(config_root)["core_version"] == BASELINE_VERSION

    automation = AutomationStore(config_root)
    rule = {
        "id": "migration-check",
        "revision": "a" * 64,
        "enabled": True,
        "action": {"plugin_id": "demo.counter", "action_ref": "demo.counter.inspect"},
        "action_hash": "b" * 64,
        "pins": {"steps": [], "providers": [{
            "plugin_id": "demo.counter", "version": "0.3.0", "provider_digest": "c" * 64,
        }]},
        "trigger": {"kind": "interval", "seconds": 3600},
        "project_ref": "migration.test",
        "next_due": UTC_NOW,
    }
    automation.put_rule(rule)
    original_run = automation.enqueue_run(automation.get_rule(rule["id"]), "migration-occurrence-1", UTC_NOW)
    assert automation.path == config_root / "automation.sqlite"
    assert automation.path.resolve() != ledger.resolve()
    assert _legacy_ledger_snapshot(ledger) == original_ledger

    candidate_source = _copy_current_release(tmp_path / "candidate-0.3.0")
    preview = deploy(candidate_source, config_root, __version__, activate=False)
    assert preview["verified"] is True
    assert preview["active"] is False
    assert verify_release(config_root, __version__)["verified"] is True
    assert json.loads((config_root / "active.json").read_text(encoding="utf-8"))["active"] == BASELINE_VERSION
    assert _launch_doctor(config_root)["core_version"] == BASELINE_VERSION

    assert activate_release(config_root, __version__)["active"] is True
    assert _launch_doctor(config_root)["core_version"] == __version__
    rolled_back = rollback(config_root)
    assert rolled_back["status"] == "succeeded"
    assert rolled_back["active"] == BASELINE_VERSION
    assert _launch_doctor(config_root)["core_version"] == BASELINE_VERSION

    assert _legacy_ledger_snapshot(ledger) == original_ledger
    retained = AutomationStore(config_root)
    assert retained.get_rule(rule["id"])["revision"] == rule["revision"]
    assert retained.show_run(original_run["run_id"])["status"] == "pending"
    assert verify_release(config_root, __version__)["verified"] is True


def test_codex_and_workbuddy_install_uninstall_are_isolated_and_preserve_user_edits(tmp_path, monkeypatch):
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("USERPROFILE", str(isolated_home))
    monkeypatch.setenv("CODEBUDDY_CONFIG_DIR", str(isolated_home / ".workbuddy"))

    config_root = tmp_path / "core"
    source = _copy_current_release(tmp_path / "release-source")
    deploy(source, config_root, __version__)

    targets = {
        "codex": ("skills", "yushuos-core", "SKILL.md"),
        "workbuddy": ("rules", "yushuos-core.md"),
    }
    legacy = {
        "codex": ("skills", "personal-system-core", "SKILL.md"),
        "workbuddy": ("rules", "personal-system-core.md"),
    }
    for host in ("codex", "workbuddy"):
        host_root = tmp_path / "host-configs" / host
        legacy_path = host_root.joinpath(*legacy[host])
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(f"keep-{host}-legacy", encoding="utf-8")
        target = host_root.joinpath(*targets[host])

        assert install_host(config_root, host_root, host=host)["installed"] is True
        installed_content = target.read_text(encoding="utf-8")
        assert "YushuOS" in installed_content
        assert uninstall_host(config_root, host_root, host=host)["removed"] is True
        assert not target.exists()
        assert legacy_path.read_text(encoding="utf-8") == f"keep-{host}-legacy"

        assert install_host(config_root, host_root, host=host)["installed"] is True
        target.write_text(f"user-edited-{host}", encoding="utf-8")
        with pytest.raises(ValueError, match="已被修改"):
            install_host(config_root, host_root, host=host)
        with pytest.raises(ValueError, match="已被修改"):
            uninstall_host(config_root, host_root, host=host)
        assert target.read_text(encoding="utf-8") == f"user-edited-{host}"
        assert legacy_path.read_text(encoding="utf-8") == f"keep-{host}-legacy"


def test_locked_v2_and_v3_plugins_install_and_explicit_version_selection(tmp_path, monkeypatch):
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("USERPROFILE", str(isolated_home))
    monkeypatch.setenv("CODEBUDDY_CONFIG_DIR", str(isolated_home / ".workbuddy"))

    config_root = tmp_path / "core"
    plugins_root = config_root / "plugins"
    v2_source = tmp_path / "versioned-v2"
    shutil.copytree(REPO_ROOT / "templates" / "plugin-template", v2_source,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    v2_manifest_path = v2_source / "plugin.yaml"
    v2_manifest = yaml.safe_load(v2_manifest_path.read_text(encoding="utf-8"))
    v2_manifest.update(id="migration.dual", name="Migration Dual", version="2.1.0")
    v2_manifest_path.write_text(yaml.safe_dump(v2_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    v3_source = tmp_path / "versioned-v3"
    shutil.copytree(REPO_ROOT / "examples" / "automation-demo" / "plugin", v3_source,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "plugin.lock.json"))
    v3_manifest_path = v3_source / "plugin.yaml"
    v3_manifest = yaml.safe_load(v3_manifest_path.read_text(encoding="utf-8"))
    v3_manifest.update(id="migration.dual", name="Migration Dual", version="3.0.0")
    v3_manifest_path.write_text(yaml.safe_dump(v3_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert lock_plugin(v2_source)["verified"] is True
    assert lock_plugin(v3_source)["verified"] is True
    assert install_plugin(v2_source, config_root)["installed"] is True
    assert install_plugin(v3_source, config_root)["installed"] is True
    assert (plugins_root / "migration.dual" / "2.1.0" / "plugin.lock.json").is_file()
    assert (plugins_root / "migration.dual" / "3.0.0" / "plugin.lock.json").is_file()

    runtime = CoreRuntime(config_root)
    assert runtime.registry.plugins["migration.dual"].version == "3.0.0"
    assert "version_selection_required" in runtime.registry.unavailable_reasons("demo.counter.inspect")

    config_path = config_root / "config.yaml"
    config_path.write_text(yaml.safe_dump({"plugins": {"versions": {"migration.dual": "2.1.0"}}}), encoding="utf-8")
    selected_v2 = CoreRuntime(config_root).registry
    assert selected_v2.plugins["migration.dual"].version == "2.1.0"
    assert selected_v2.plugins["migration.dual"].contract_version == 2
    assert selected_v2.resolve("example.echo") is not None

    config_path.write_text(yaml.safe_dump({
        "plugins": {"versions": {"migration.dual": "3.0.0"}},
        "permissions": {"grants": ["demo.counter.write"]},
    }), encoding="utf-8")
    selected_v3 = CoreRuntime(config_root).registry
    assert selected_v3.plugins["migration.dual"].version == "3.0.0"
    assert selected_v3.plugins["migration.dual"].contract_version == 3
    binding = selected_v3.resolve("demo.counter.inspect")
    assert binding is not None
    assert binding.plugin.runner["protocol"] == "json-stdio-v2"


def test_launcher_failure_is_json_under_ascii_output_encoding(tmp_path):
    from yushuos.deployment import _write_launcher
    _write_launcher(tmp_path)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "ascii"
    result = subprocess.run([sys.executable, str(tmp_path / "bin" / "yushuos.py"), "doctor"],
                            capture_output=True, encoding="ascii", env=env, timeout=20)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "failed"
    assert "UnicodeEncodeError" not in result.stderr
