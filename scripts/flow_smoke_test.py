from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_plugins.contracts import ActivationState, Availability, PluginManifest
from capability_plugins.lifecycle import PluginLifecycle
from capability_plugins.loader import load_manifests
from capability_plugins.registry import PluginRegistry
from experience_layer import ExperienceRequest
from experience_layer.flows.adjust import AdjustFlow
from experience_layer.flows.capture import CaptureFlow
from experience_layer.flows.explore import ExploreFlow
from experience_layer.flows.plan import PlanFlow
from experience_layer.flows.review import ReviewFlow
from experience_layer.flows.today import TodayFlow
from experience_layer.service import ExperienceService
from orchestration import FlowName
from orchestration.executor import Executor
from orchestration.planner import CapabilityPlanner
from runtime_core import AgentDefinition, RuntimeKernel


MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
FLOW_ORDER = (
    FlowName.CAPTURE,
    FlowName.PLAN,
    FlowName.TODAY,
    FlowName.ADJUST,
    FlowName.REVIEW,
    FlowName.EXPLORE,
)
SCENARIOS = ("normal", "plugin_unavailable", "permission_denied", "partial_failure")


class OfflinePlugin:
    """Deterministic local fixture plugin; it never calls an external service."""

    def __init__(self, manifest: PluginManifest, *, scenario: str) -> None:
        self.manifest = manifest
        self.scenario = scenario
        self.rollback_count = 0

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]):
        if (
            self.scenario == "partial_failure"
            and context.get("flow") == FlowName.PLAN.value
            and capability == "task.create_proposal"
        ):
            raise RuntimeError("offline fixture failure")
        return _fixture_result(capability)

    def rollback(
        self,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any],
        result: Any,
    ) -> str:
        del capability, payload, context, result
        self.rollback_count += 1
        return "simulated"


def _fixture_result(capability: str) -> Any:
    if capability == "information.capture":
        return {"object_id": "info-smoke-1"}
    if capability == "task.list":
        return {"tasks": []}
    if capability == "calendar.list_events":
        return {"events": []}
    if capability == "body.current_energy":
        return {"today_energy_context": {"body_battery_score": 72, "sleep_hours": 7.2}}
    if capability in {"task.create_proposal", "task.update_proposal"}:
        return {"proposal_id": "task-proposal-smoke", "status": "pending_human_review"}
    if capability == "goal.parse":
        return {"goal_id": "goal-smoke"}
    if capability in {"project.create_proposal", "project.milestone_proposal"}:
        return {"proposal_id": f"{capability.rsplit('.', 1)[-1]}-smoke", "status": "pending_human_review"}
    if capability == "project.context":
        return {
            "behaviors": [{"title": "完成一次项目检查"}],
            "results": [{"title": "识别一个风险"}],
            "trends": [],
            "problems": [],
            "cause_hypotheses": [],
            "recommendations": [{"title": "下周继续检查"}],
        }
    if capability == "learning.progress":
        return {"completed": 4, "target": 8}
    if capability == "knowledge.search":
        return {
            "items": [
                {
                    "title": "启动延迟趋势",
                    "summary": "过去四周下午任务的启动时间更晚。",
                    "source": "fixture.task_history",
                    "observed_at": "2026-09-26",
                    "confidence": 0.82,
                }
            ]
        }
    return {}


def _manifests(scenario: str) -> tuple[PluginManifest, ...]:
    manifests = load_manifests(MANIFEST_DIR)
    if scenario == "plugin_unavailable":
        manifests = tuple(
            replace(manifest, availability=Availability.UNAVAILABLE)
            if manifest.plugin_id == "knowledge"
            else manifest
            for manifest in manifests
        )
    return manifests


def _activate_smoke_plugins(registry: PluginRegistry) -> None:
    lifecycle = PluginLifecycle(registry)
    for plugin_id in ("body", "goal", "project", "learning"):
        lifecycle.transition(
            plugin_id,
            activation_state=ActivationState.ACTIVE,
            actor="smoke_test",
            reason="offline_smoke_fixture",
        )


def _request(flow: FlowName) -> ExperienceRequest:
    requests = {
        FlowName.CAPTURE: ExperienceRequest(
            text="我答应周五前把资料发给李明",
            correlation_id="corr-smoke-capture",
            structured_flow=flow,
        ),
        FlowName.PLAN: ExperienceRequest(
            text="帮我实现英语能力提升目标",
            correlation_id="corr-smoke-plan",
            structured_flow=flow,
            context={
                "goal": {"goal_id": "goal-smoke", "title": "提升英语能力"},
                "current_state": {"level": "B1", "weekly_hours": 3},
                "gaps": [
                    {
                        "gap_id": "gap-smoke",
                        "title": "听力理解需要提升",
                        "current": "需要字幕辅助",
                        "desired": "理解日常对话",
                    }
                ],
                "project_plan": {
                    "project": {"project_id": "project-smoke", "title": "英语提升"},
                    "milestones": [
                        {"milestone_id": "milestone-smoke", "title": "建立听力习惯"}
                    ],
                    "tasks": [
                        {
                            "task_guid": "task-smoke",
                            "title": "完成一次英语听力练习",
                            "deadline": "2026-10-04",
                            "movable": True,
                            "estimated_minutes": 30,
                        }
                    ],
                    "calendar_proposals": [],
                },
            },
        ),
        FlowName.TODAY: ExperienceRequest(
            text="今天有什么待办",
            correlation_id="corr-smoke-today",
            structured_flow=flow,
            context={
                "target_date": "2026-09-27",
                "body_snapshot": {
                    "today_energy_context": {
                        "body_battery_score": 72,
                        "sleep_hours": 7.2,
                    }
                },
            },
        ),
        FlowName.ADJUST: ExperienceRequest(
            text="帮我调整今天安排",
            correlation_id="corr-smoke-adjust",
            structured_flow=flow,
            context={
                "energy": {
                    "level": "normal",
                    "observed_on": "2026-09-27",
                    "fresh": True,
                },
                "items": [],
                "candidate_slots": [],
            },
        ),
        FlowName.REVIEW: ExperienceRequest(
            text="复盘本周",
            correlation_id="corr-smoke-review",
            structured_flow=flow,
            context={"period": "2026-W39"},
        ),
        FlowName.EXPLORE: ExperienceRequest(
            text="最近为什么总拖延？",
            correlation_id="corr-smoke-explore",
            structured_flow=flow,
            context={"time_range": "2026-09-01/2026-09-27"},
        ),
    }
    return requests[flow]


def _expected_scenario(report: dict[str, Any], scenario: str) -> bool:
    by_flow = {item["flow"]: item["status"] for item in report["flows"]}
    event_names = {event["event"] for event in report["events"]}
    successful_statuses = {"completed", "partial", "needs_clarification"}
    if scenario == "plugin_unavailable":
        return (
            by_flow["explore"] == "blocked"
            and all(
                status in successful_statuses
                for flow, status in by_flow.items()
                if flow != "explore"
            )
        )
    if scenario == "permission_denied":
        return (
            by_flow["capture"] == "partial"
            and "policy_blocked" in event_names
            and all(
                status in successful_statuses
                for flow, status in by_flow.items()
                if flow != "capture"
            )
        )
    if scenario == "partial_failure":
        rollback = next(
            (
                event
                for event in report["events"]
                if event["event"] == "rollback_completed"
            ),
            None,
        )
        return (
            by_flow["plan"] == "partial"
            and rollback is not None
            and rollback.get("status") == "simulated"
            and "plugin_failed" in event_names
            and all(
                status in successful_statuses
                for flow, status in by_flow.items()
                if flow != "plan"
            )
        )
    return all(by_flow[flow.value] in successful_statuses for flow in FLOW_ORDER)


def run_smoke(*, scenario: str = "normal") -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unsupported smoke scenario: {scenario}")

    with tempfile.TemporaryDirectory(prefix="yushu-flow-smoke-") as state_dir:
        manifests = _manifests(scenario)
        registry = PluginRegistry.from_manifests(manifests)
        _activate_smoke_plugins(registry)
        permissions = sorted(
            {permission for manifest in manifests for permission in manifest.permissions}
        )
        if scenario == "permission_denied":
            permissions.remove("propose_task_change")
        kernel = RuntimeKernel(
            gateway=object(),
            state_path=Path(state_dir) / "runtime",
            local_model="offline-fixture",
            cloud_model="offline-fixture",
            default_network_mode="OFF",
            plugin_registry=registry,
        )
        kernel.register_agent(
            AgentDefinition(
                agent_id="experience_agent",
                name="Offline Experience Fixture",
                domain="experience",
                autonomy_level=2,
                risk_level="medium",
                permissions=tuple(permissions),
                handler=lambda context: None,
            )
        )
        planner = CapabilityPlanner(registry, events=kernel.events)
        plugins = {
            manifest.plugin_id: OfflinePlugin(
                registry.get(manifest.plugin_id), scenario=scenario
            )
            for manifest in manifests
        }
        executor = Executor(kernel, plugins)
        agent_id = "experience_agent"
        handlers = {
            FlowName.CAPTURE: CaptureFlow(planner, executor, agent_id=agent_id),
            FlowName.PLAN: PlanFlow(planner, executor, agent_id=agent_id),
            FlowName.TODAY: TodayFlow(planner, executor, agent_id=agent_id),
            FlowName.ADJUST: AdjustFlow(),
            FlowName.REVIEW: ReviewFlow(planner, executor, agent_id=agent_id),
            FlowName.EXPLORE: ExploreFlow(planner, executor, agent_id=agent_id),
        }
        service = ExperienceService(handlers, events=kernel.events)
        flow_results = []
        for flow in FLOW_ORDER:
            response = service.handle(_request(flow))
            flow_results.append({"flow": flow.value, "status": response.status})

        report: dict[str, Any] = {
            "scenario": scenario,
            "network_mode": kernel.default_network_mode,
            "flows": flow_results,
            "events": kernel.events.history,
        }
        report["ok"] = (
            len(flow_results) == len(FLOW_ORDER)
            and tuple(item["flow"] for item in flow_results)
            == tuple(flow.value for flow in FLOW_ORDER)
            and kernel.default_network_mode == "OFF"
            and _expected_scenario(report, scenario)
        )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run six Yushu flows with local fixtures and network OFF."
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report = run_smoke(scenario=args.scenario)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"offline flow smoke | scenario={args.scenario} | network={report['network_mode']}")
        for item in report["flows"]:
            print(f"{item['flow']}: {item['status']}")
        print("result: PASS" if report["ok"] else "result: FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
