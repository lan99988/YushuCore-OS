from __future__ import annotations

import json
from pathlib import Path
from agents.information_pipeline import InformationPipeline
from capability_plugins import (
    ActivationState,
    PluginLifecycle,
    PluginRegistry,
    load_manifests,
)
from capability_plugins.body import BodyPlugin
from capability_plugins.calendar import CalendarPlugin
from capability_plugins.finance import FinancePlugin
from capability_plugins.information import InformationPlugin
from capability_plugins.task import TaskPlugin
from experience_layer import ExperienceRequest, ExperienceService
from experience_layer.flows.capture import CaptureFlow
from experience_layer.flows.review import ReviewFlow
from experience_layer.flows.today import TodayFlow
from information_system import InformationStore
from orchestration import CapabilityPlanner, Executor
from orchestration import FlowName, IntentRouter, UserIntent
from runtime_core import AgentDefinition, RuntimeKernel


ROOT = Path(__file__).resolve().parents[2]


def _assert_route(text: str, expected: FlowName) -> None:
    routed = IntentRouter().route(text)
    assert isinstance(routed, UserIntent), (text, routed)
    assert routed.flow is expected


def test_scenario_1_task_input_routes_to_capture_without_structured_hint():
    _assert_route("周五前交项目报告。", FlowName.CAPTURE)


def test_scenario_3_goal_input_routes_to_plan_without_structured_hint():
    _assert_route("两个月完成专业课第一轮。", FlowName.PLAN)


def test_scenario_5_sleep_input_routes_to_adjust_without_structured_hint():
    _assert_route("昨晚只睡 5 小时。", FlowName.ADJUST)


def test_scenario_8_passport_input_routes_to_capture_without_structured_hint():
    _assert_route("护照明年 3 月到期。", FlowName.CAPTURE)


def test_scenario_1_capture_task_from_one_natural_language_input(tmp_path):
    manifests = tuple(
        manifest
        for manifest in load_manifests(ROOT / "capability_plugins" / "manifests")
        if manifest.plugin_id in {"information", "task"}
    )
    registry = PluginRegistry.from_manifests(manifests)
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="experience_agent",
            name="Experience Agent",
            domain="experience",
            autonomy_level=2,
            risk_level="medium",
            permissions=("ingest_information", "propose_task_change"),
            handler=lambda context: None,
        )
    )
    store = InformationStore(tmp_path / "information.db")
    store.init_schema()
    manifest_by_id = {item.plugin_id: item for item in manifests}
    class RecordingTaskPlugin:
        def __init__(self):
            self.inner = TaskPlugin()
            self.manifest = self.inner.manifest
            self.calls = []

        def invoke(self, capability, payload, context):
            self.calls.append((capability, dict(payload)))
            return self.inner.invoke(capability, payload, context)

    task_plugin = RecordingTaskPlugin()
    plugins = {
        "information": InformationPlugin(
            manifest_by_id["information"], InformationPipeline(store)
        ),
        "task": task_plugin,
    }
    response = ExperienceService(
        {
            FlowName.CAPTURE: CaptureFlow(
                CapabilityPlanner(registry),
                Executor(kernel, plugins),
                agent_id="experience_agent",
            )
        }
    ).handle(ExperienceRequest(
        text="周五前交项目报告。",
        correlation_id="corr-final-capture-task",
    ))

    assert response.status == "completed", (response, response.uncertainties)
    assert any(item.reason_code == "task_recognized" for item in response.understood)
    assert len(response.recorded) == 2
    assert any(item.reason_code == "task_proposed" for item in response.recorded)
    assert response.confirmations == ()
    assert len(store.list_objects(status="inbox")) == 1
    assert task_plugin.calls == [
        (
            "task.create_proposal",
            {
                "title": "交项目报告",
                "evidence": ["周五前交项目报告。"],
                "due_at": "周五",
                "affects_commitment": False,
                "external_commitment": False,
            },
        )
    ]
    audit_text = (tmp_path / "runtime" / "audit.jsonl").read_text(encoding="utf-8")
    assert "周五前交项目报告" not in audit_text


def test_scenario_10_calendar_unavailable_returns_partial_and_recovery_guidance(
    tmp_path,
):
    manifests = tuple(
        manifest
        for manifest in load_manifests(ROOT / "capability_plugins" / "manifests")
        if manifest.plugin_id in {"calendar", "task", "body"}
    )
    registry = PluginRegistry.from_manifests(manifests)
    PluginLifecycle(registry).transition(
        "body",
        activation_state=ActivationState.ACTIVE,
        actor="acceptance",
        reason="today_energy_fixture",
    )
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        default_network_mode="ASSIST",
        plugin_registry=registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="experience_agent",
            name="Experience Agent",
            domain="experience",
            autonomy_level=2,
            risk_level="medium",
            permissions=("read_calendar", "read_task", "read_body_snapshot"),
            handler=lambda context: None,
        )
    )
    body = BodyPlugin()
    body.manifest = registry.get("body")
    plugins = {
        "calendar": CalendarPlugin(),
        "task": TaskPlugin(
            delegates={
                "task.list": lambda filters: [
                    {
                        "task_guid": "task-final-available",
                        "title": "完成可用任务",
                        "priority": "P1",
                        "movable": True,
                    }
                ]
            }
        ),
        "body": body,
    }
    request = ExperienceRequest(
        text="今天应该怎么过？",
        correlation_id="corr-final-calendar-unavailable",
        structured_flow=FlowName.TODAY,
        context={
            "target_date": "2026-09-27",
            "body_snapshot": {
                "today_energy_context": {
                    "body_battery_score": 70,
                    "sleep_hours": 7.5,
                }
            },
        },
    )
    intent = UserIntent(
        flow=FlowName.TODAY,
        text=request.text,
        confidence=1.0,
        evidence=("structured",),
        correlation_id=request.correlation_id,
    )

    response = TodayFlow(
        CapabilityPlanner(registry),
        Executor(kernel, plugins),
        agent_id="experience_agent",
    ).run(request, intent)

    assert response.status == "partial"
    assert any(item.reason_code == "high_priority_task" for item in response.suggestions)
    assert len(response.uncertainties) == 1
    assert response.uncertainties[0].reason_code == "calendar_module_unavailable"
    assert "日历" in response.uncertainties[0].title
    assert dict(response.diagnostics[0]) == {
        "step_id": "today-calendar",
        "capability": "calendar.list_events",
        "status": "unavailable",
        "reason_code": "calendar_module_unavailable",
    }


def test_scenario_6_review_finance_screenshot_through_governed_runtime(tmp_path):
    fixture_dir = ROOT / "tests" / "fixtures" / "finance"

    def fixture(name):
        return json.loads((fixture_dir / name).read_text(encoding="utf-8"))

    class OCR:
        def extract_monthly_summary(self, image_refs, *, month):
            assert image_refs == ("fixture://finance/2026-09",)
            assert month == "2026-09"
            return fixture("ocr_2026-09.json")

    class History:
        def previous_month_summary(self, month):
            assert month == "2026-09"
            return fixture("history_2026-08.json")

    class Analysis:
        def analyze_monthly_snapshot(self, snapshot, previous_summary):
            assert snapshot["month"] == "2026-09"
            assert previous_summary["month"] == "2026-08"
            return fixture("analysis_2026-09.json")

    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "finance"
    )
    registry = PluginRegistry.from_manifests((manifest,))
    PluginLifecycle(registry).transition(
        "finance",
        activation_state=ActivationState.ACTIVE,
        actor="acceptance",
        reason="monthly_snapshot_uploaded",
    )
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="experience_agent",
            name="Experience Agent",
            domain="experience",
            autonomy_level=2,
            risk_level="medium",
            permissions=("read_finance", "propose_change"),
            handler=lambda context: None,
        )
    )
    finance = FinancePlugin(
        ocr_port=OCR(),
        history_port=History(),
        analysis_port=Analysis(),
    )
    finance.manifest = registry.get("finance")
    flow = ReviewFlow(
        CapabilityPlanner(registry),
        Executor(
            kernel,
            {"finance": finance},
        ),
        agent_id="experience_agent",
    )
    request = ExperienceRequest(
        text="复盘 2026 年 9 月财务截图",
        correlation_id="corr-final-finance-review",
        structured_flow=FlowName.REVIEW,
        context={
            "finance_month": "2026-09",
            "finance_image_refs": ["fixture://finance/2026-09"],
        },
    )
    intent = UserIntent(
        flow=FlowName.REVIEW,
        text=request.text,
        confidence=1.0,
        evidence=("structured",),
        correlation_id=request.correlation_id,
    )

    response = flow.run(request, intent)

    assert response.status == "completed", (response, response.uncertainties)
    snapshot = next(
        item for item in response.understood if item.reason_code == "result_observed"
    )
    assert snapshot.after == {
        "month": "2026-09",
        "total_income": 12000,
        "total_expenses": 8000,
        "balance": 4000,
        "savings_rate": 1 / 3,
    }
    assert any("餐饮" in item.title for item in response.understood)
    assert {item.title for item in response.suggestions} == {
        "建议：关注餐饮支出",
        "建议：维持储蓄水平",
    }
