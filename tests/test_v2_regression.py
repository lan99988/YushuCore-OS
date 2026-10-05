"""Golden CLI and storage compatibility checks captured from the v2 baseline."""

import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import yaml

from yushuos.deployment import lock_plugin


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "v2"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _install_fixture_plugin(config_root: Path, *, write: bool = False) -> Path:
    plugin = config_root / "plugins" / "example.echo"
    plugin.mkdir(parents=True)
    for name in ("plugin.yaml", "run.py"):
        shutil.copyfile(FIXTURES / name, plugin / name)
    if write:
        manifest_path = plugin / "plugin.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["permissions"] = ["calendar.write"]
        capability = manifest["capabilities"][0]
        capability["effect"] = "external_write"
        capability["intents"] = ["write"]
        capability["permissions"] = ["calendar.write"]
        manifest_path.write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    lock_plugin(plugin)
    return plugin


def _cli(tmp_path: Path, config_root: Path, *args: str, value=None) -> dict:
    host_home = tmp_path / "isolated-host-home"
    host_home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({
        "HOME": str(host_home),
        "USERPROFILE": str(host_home),
        "CODEBUDDY_CONFIG_DIR": str(host_home),
        "PYTHONUTF8": "1",
    })
    process = subprocess.run(
        [sys.executable, "-m", "yushuos", "--config-root", str(config_root), *args],
        input=None if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    assert process.stderr == ""
    assert len(process.stdout.splitlines()) == 1, process.stdout
    return json.loads(process.stdout)


def _normalize_workflow_status(value: dict) -> dict:
    normalized = copy.deepcopy(value)
    run = normalized["run"]
    for key in ("created", "updated"):
        if key in run:
            run[key] = "<timestamp>"
    for step in normalized["steps"]:
        if "updated" in step:
            step["updated"] = "<timestamp>"
    return normalized


def _request() -> dict:
    return {
        "request_id": "baseline-invoke-1",
        "capability": "example.echo",
        "intent": "read",
        "fields": {"message": "hello from baseline"},
    }


def _write_request() -> dict:
    return {
        "request_id": "baseline-write-invoke-1",
        "capability": "example.echo",
        "intent": "write",
        "fields": {"message": "should stay preview"},
    }


def _plan() -> dict:
    return {"steps": [{
        "step_id": "baseline-step-1",
        "request_id": "baseline-workflow-1",
        "capability": "example.echo",
        "intent": "read",
        "fields": {"message": "hello from baseline"},
    }]}


def test_v2_cli_json_outputs_match_the_frozen_default_contract(tmp_path):
    config_root = tmp_path / "core"
    _install_fixture_plugin(config_root)
    expected = _load_fixture("cli.json")

    doctor = _cli(tmp_path, config_root, "doctor")
    doctor["core_version"] = "<core-version>"
    assert doctor == expected["doctor"]

    assert _cli(tmp_path, config_root, "catalog") == expected["catalog"]
    assert _cli(tmp_path, config_root, "parse", "--text", "#example hello from baseline") == expected["parse_routed"]
    assert _cli(tmp_path, config_root, "parse", "--text", "hello from baseline") == expected["parse_handoff"]

    # The manifest and runner in this fixture are the v2 json-stdio plugin protocol.
    # The CLI default invocation is preview mode and still returns the complete Result shape.
    assert _cli(tmp_path, config_root, "invoke", value=_request()) == expected["invoke_preview"]
    assert _cli(tmp_path, config_root, "workflow", value=_plan()) == expected["workflow_preview"]

    write_root = tmp_path / "write-core"
    _install_fixture_plugin(write_root, write=True)
    (write_root / "config.yaml").write_text(
        yaml.safe_dump({"permissions": {"grants": ["calendar.write"], "denials": []}}, sort_keys=False),
        encoding="utf-8",
    )
    assert _cli(tmp_path, write_root, "invoke", value=_write_request()) == expected["invoke_write_preview"]
    assert not (write_root / "plugin-data").exists()


def test_workflow_cli_extends_and_preserves_the_existing_v01_ledger(tmp_path):
    config_root = tmp_path / "core"
    _install_fixture_plugin(config_root)
    ledger = config_root / "operations.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.executescript((FIXTURES / "legacy-ledger.sql").read_text(encoding="utf-8"))
    (config_root / "config.yaml").write_text(
        yaml.safe_dump({"state": {"ledger_path": ledger.name}}, sort_keys=False),
        encoding="utf-8",
    )

    expected = _load_fixture("workflow-execute.json")
    actual_workflow = _cli(
        tmp_path,
        config_root,
        "workflow",
        "--mode",
        "execute",
        "--host-mode",
        "execute",
        value=_plan(),
    )
    assert actual_workflow == expected["workflow_execute"]

    plan_id = actual_workflow["plan_id"]
    status = _cli(tmp_path, config_root, "status", "--plan-id", plan_id)
    assert _normalize_workflow_status(status) == expected["workflow_status"]
    assert _cli(tmp_path, config_root, "status", "--request-id", "legacy-request-1") == expected["legacy_receipt"]

    with sqlite3.connect(ledger) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"operations", "locks", "events", "workflow_runs", "workflow_steps"} <= tables
        legacy_operation = db.execute(
            "SELECT request_id, fingerprint, resource_key, status, receipt, updated FROM operations"
        ).fetchone()
        assert legacy_operation == (
            "legacy-request-1",
            "legacy-fingerprint",
            "request:legacy-request-1",
            "succeeded",
            '{"status":"succeeded","request_id":"legacy-request-1","message":"legacy receipt retained","resource":{},"data":null,"error":null}',
            "2025-01-02T03:04:05+00:00",
        )
        assert json.loads(legacy_operation[4]) == expected["legacy_receipt"]["receipt"]
        assert db.execute("SELECT resource_key, request_id FROM locks").fetchall() == [
            ("legacy-resource:calendar-1", "legacy-pending-request"),
        ]
        assert db.execute("SELECT calendar_id, event_id, task_guid, snapshot FROM events").fetchall() == [(
            "calendar-1",
            "event-1",
            "task-1",
            '{"title":"legacy event snapshot","start":"2025-01-02T09:00:00+08:00"}',
        )]

    assert b"hello from baseline" not in ledger.read_bytes()
