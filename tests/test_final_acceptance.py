from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _api():
    from scripts import final_acceptance

    return final_acceptance


def test_final_acceptance_declares_all_ten_product_scenarios():
    final_acceptance = _api()

    scenarios = final_acceptance.PRODUCT_SCENARIOS

    assert tuple(scenarios) == tuple(range(1, 11))
    assert all(item.scenario_id == scenario_id for scenario_id, item in scenarios.items())
    assert all(item.title.strip() and item.pytest_targets for item in scenarios.values())
    assert len(
        {
            target
            for item in scenarios.values()
            for target in item.pytest_targets
        }
    ) >= 10


def test_final_acceptance_runner_reports_each_scenario_without_hiding_failure():
    final_acceptance = _api()
    calls = []

    def fake_runner(targets):
        calls.append(tuple(targets))
        return 1 if any("scenario_10" in target for target in targets) else 0

    report = final_acceptance.run_acceptance(runner=fake_runner)

    assert len(calls) == 10
    assert report["ok"] is False
    assert [item["scenario_id"] for item in report["scenarios"]] == list(range(1, 11))
    assert report["scenarios"][-1]["status"] == "failed"
    assert all(item["status"] == "passed" for item in report["scenarios"][:-1])


def test_final_acceptance_targets_are_real_collectable_tests():
    final_acceptance = _api()
    targets = [
        target
        for item in final_acceptance.PRODUCT_SCENARIOS.values()
        for target in item.pytest_targets
    ]

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *targets],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_final_acceptance_cli_lists_scenarios_as_json_without_running_them():
    completed = subprocess.run(
        [sys.executable, "scripts/final_acceptance.py", "--list", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["network_mode"] == "OFF"
    assert len(report["scenarios"]) == 10
    assert all(item["status"] == "not_run" for item in report["scenarios"])


def test_release_documents_publish_the_verified_v1_entrypoints():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blueprint = (
        ROOT / "07_系统文档（Docs）" / "SYSTEM_BLUEPRINT.md"
    ).read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for document in (readme, blueprint, changelog):
        assert "Yushu Adaptive OS v1.0" in document
    assert "scripts/final_acceptance.py" in readme
    assert "Capture / Plan / Today / Adjust / Review / Explore" in blueprint
