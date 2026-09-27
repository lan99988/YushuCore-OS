from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.health_check import check_config


@dataclass(frozen=True)
class ProductScenario:
    scenario_id: int
    title: str
    pytest_targets: tuple[str, ...]


PRODUCT_SCENARIOS = {
    1: ProductScenario(
        1,
        "Capture 任务：周五前交项目报告",
        (
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_1_capture_task_from_one_natural_language_input",
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_1_task_input_routes_to_capture_without_structured_hint",
        ),
    ),
    2: ProductScenario(
        2,
        "Capture 社交承诺：周末给李明发资料",
        (
            "tests/e2e/test_capture_today_adjust.py::"
            "test_capture_creates_proposal_for_external_commitment",
        ),
    ),
    3: ProductScenario(
        3,
        "Plan：两个月完成专业课第一轮",
        (
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_3_goal_input_routes_to_plan_without_structured_hint",
            "tests/experience/test_plan_flow.py::"
            "test_plan_builds_distinct_goal_state_gap_project_milestone_task_and_calendar_proposal",
        ),
    ),
    4: ProductScenario(
        4,
        "Today：固定会议、到期任务与低身体能量",
        (
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_5_sleep_input_routes_to_adjust_without_structured_hint",
            "tests/e2e/test_capture_today_adjust.py::"
            "test_today_aggregates_offline_sources_without_exposing_plugins",
            "tests/experience/test_today_flow.py::"
            "test_commitment_or_due_task_is_never_automatically_rescheduled_or_downgraded",
        ),
    ),
    5: ProductScenario(
        5,
        "Adjust：昨晚只睡 5 小时",
        (
            "tests/e2e/test_capture_today_adjust.py::"
            "test_low_energy_replans_movable_tasks_but_preserves_commitments",
        ),
    ),
    6: ProductScenario(
        6,
        "Review：月度财务截图 fixture",
        (
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_6_review_finance_screenshot_through_governed_runtime",
            "tests/plugins/test_finance_plugin.py::"
            "test_fixed_offline_fixtures_produce_a_reviewable_monthly_snapshot",
        ),
    ),
    7: ProductScenario(
        7,
        "Explore：最近为什么总拖延",
        (
            "tests/e2e/test_review_explore_plugins.py::"
            "test_explore_reads_real_knowledge_plugin_through_governed_runtime",
        ),
    ),
    8: ProductScenario(
        8,
        "Life Admin：首次提到护照到期",
        (
            "tests/e2e/test_on_demand_capture_domains.py::"
            "test_passport_capture_activates_only_life_admin_and_returns_reviewable_reminder",
        ),
    ),
    9: ProductScenario(
        9,
        "Interest：记录兴趣但不创建 KPI",
        (
            "tests/e2e/test_on_demand_capture_domains.py::"
            "test_interest_capture_activates_interest_without_creating_task_or_kpi",
            "tests/e2e/test_on_demand_capture_domains.py::"
            "test_explore_reviews_approved_interest_events_through_read_only_plugin",
            "tests/plugins/test_interest_plugin.py::"
            "test_interest_schema_has_no_kpi_streak_or_target_fields",
        ),
    ),
    10: ProductScenario(
        10,
        "故障：Calendar Plugin 不可用时返回部分结果和恢复提示",
        (
            "tests/e2e/test_final_product_scenarios.py::"
            "test_scenario_10_calendar_unavailable_returns_partial_and_recovery_guidance",
        ),
    ),
}


Runner = Callable[[Iterable[str]], int]


def _pytest_runner(targets: Iterable[str]) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tuple(targets)],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


def _scenario_rows(status: str = "not_run") -> list[dict[str, object]]:
    return [
        {
            "scenario_id": scenario.scenario_id,
            "title": scenario.title,
            "status": status,
            "pytest_targets": list(scenario.pytest_targets),
        }
        for scenario in PRODUCT_SCENARIOS.values()
    ]


def run_acceptance(*, runner: Runner | None = None) -> dict[str, object]:
    execute = runner or _pytest_runner
    rows = []
    for scenario in PRODUCT_SCENARIOS.values():
        return_code = execute(scenario.pytest_targets)
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "status": "passed" if return_code == 0 else "failed",
                "return_code": return_code,
                "pytest_targets": list(scenario.pytest_targets),
            }
        )
    network_mode = check_config(ROOT / "config")["network_mode"]
    return {
        "ok": all(row["status"] == "passed" for row in rows)
        and network_mode == "OFF",
        "network_mode": network_mode,
        "scenarios": rows,
    }


def _listed_report() -> dict[str, object]:
    return {
        "ok": None,
        "network_mode": check_config(ROOT / "config")["network_mode"],
        "scenarios": _scenario_rows(),
    }


def _render_text(report: dict[str, object]) -> str:
    lines = [f"Yushu final acceptance | network={report['network_mode']}"]
    for row in report["scenarios"]:
        lines.append(
            f"{row['scenario_id']:02d}. {row['status']}: {row['title']}"
        )
    if report["ok"] is not None:
        lines.append("result: PASS" if report["ok"] else "result: FAIL")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the ten offline Yushu product acceptance scenarios."
    )
    parser.add_argument("--list", action="store_true", help="list without running")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    report = _listed_report() if args.list else run_acceptance()
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_text(report))
    return 0 if args.list or report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
