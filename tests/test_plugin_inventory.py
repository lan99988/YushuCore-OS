from __future__ import annotations

import json
import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _plugin_inventory():
    assert importlib.util.find_spec("scripts.plugin_inventory") is not None, (
        "scripts.plugin_inventory is required"
    )
    return importlib.import_module("scripts.plugin_inventory")


def test_plugin_inventory_lists_state_and_capabilities_from_manifests():
    plugin_inventory = _plugin_inventory()
    items = plugin_inventory.collect_inventory(ROOT / "capability_plugins" / "manifests")

    assert items
    assert [item["plugin_id"] for item in items] == sorted(
        item["plugin_id"] for item in items
    )
    task = next(item for item in items if item["plugin_id"] == "task")
    assert task["status"] == "ready"
    assert "task.create_proposal" in task["capabilities"]
    assert task["domain"] == "task"


def test_plugin_inventory_command_prints_machine_readable_status(capsys):
    plugin_inventory = _plugin_inventory()
    plugin_inventory.main(
        [
            "--format",
            "json",
            "--manifests",
            str(ROOT / "capability_plugins" / "manifests"),
        ]
    )

    rendered = json.loads(capsys.readouterr().out)
    assert any(
        item["plugin_id"] == "information"
        and "information.capture" in item["capabilities"]
        for item in rendered
    )


def test_plugin_inventory_script_runs_as_one_command():
    result = subprocess.run(
        [sys.executable, "scripts/plugin_inventory.py", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)


def test_health_check_reports_plugin_readiness_without_changing_network_policy():
    from scripts import health_check

    assert hasattr(health_check, "check_plugin_inventory"), (
        "health_check must report plugin readiness"
    )
    report = health_check.check_plugin_inventory(
        ROOT / "capability_plugins" / "manifests"
    )

    assert report["plugin_count"] > 0
    assert report["ready_count"] > 0
    assert report["capability_count"] > 0
    assert health_check.check_config(ROOT / "config")["network_mode"] == "OFF"
