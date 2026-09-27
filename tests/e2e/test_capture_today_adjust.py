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
from capability_plugins.information import InformationPlugin
from capability_plugins.task import TaskPlugin
from experience_layer import ExperiencePresenter, ExperienceRequest, ExperienceService
from experience_layer.flows.capture import CaptureFlow
from experience_layer.flows.adjust import AdjustFlow
from experience_layer.flows.today import TodayFlow
from information_system import InformationStore
from orchestration import CapabilityPlanner, Executor, FlowName
from runtime_core import AgentDefinition, RuntimeKernel


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"


def _manifests(*plugin_ids):
    selected = {
        manifest.plugin_id: manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id in set(plugin_ids)
    }
    assert set(selected) == set(plugin_ids)
    return selected


def test_capture_creates_proposal_for_external_commitment(tmp_path):
    manifests = _manifests("information", "task")
    registry = PluginRegistry.from_manifests(manifests.values())
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
    plugins = {
        "information": InformationPlugin(
            manifests["information"], InformationPipeline(store)
        ),
        "task": TaskPlugin(),
    }
    flow = CaptureFlow(
        CapabilityPlanner(registry),
        Executor(kernel, plugins),
        agent_id="experience_agent",
    )
    service = ExperienceService({FlowName.CAPTURE: flow})

    response = service.handle(
        ExperienceRequest(
            text="我答应周五前把资料发给李明",
            correlation_id="corr-e2e-capture",
        )
    )
    public = ExperiencePresenter().present(response)

    assert response.status == "partial"
    assert any("李明" in item.title for item in response.understood)
    assert {item.reason_code for item in response.understood} == {
        "person_recognized",
        "commitment_recognized",
        "task_recognized",
    }
    assert response.recorded[0].reason_code == "information_recorded"
    assert response.confirmations[0].reason_code == (
        "approval_required_external_commitment"
    )
    assert response.confirmations[0].requires_confirmation is True
    assert len(store.list_objects(status="inbox")) == 1
    assert "send_message" not in repr(response.diagnostics)
    assert "plugin" not in repr(public).casefold()
    assert not any(
        marker in repr(public)
        for marker in ("information.capture", "task.create_proposal")
    )
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "runtime" / "audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    commitment_audit = next(
        item
        for item in audit_records
        if item["capability"] == "task.create_proposal"
    )
    assert commitment_audit["reason_code"] == (
        "approval_required_external_commitment"
    )
    assert commitment_audit["result"] == "pending_approval"
    assert "把资料发给李明" not in repr(audit_records)


class OfflineCalendar:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def check_date_freebusy(self, target_date=None):
        self.calls.append(target_date)
        return self.events


def test_today_aggregates_offline_sources_without_exposing_plugins(tmp_path):
    manifests = _manifests("calendar", "task", "body")
    registry = PluginRegistry.from_manifests(manifests.values())
    PluginLifecycle(registry).transition(
        "body",
        activation_state=ActivationState.ACTIVE,
        actor="test",
        reason="today_fixture",
    )
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "today-runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
        default_network_mode="ASSIST",
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
    events = [
        {
            "event_id": "meeting-1400",
            "summary": "14:00 固定会议",
            "start": "2026-09-27T14:00:00+08:00",
            "end": "2026-09-27T15:00:00+08:00",
            "fixed_meeting": True,
            "external_commitment": True,
        }
    ]
    tasks = [
        {
            "task_guid": "task-deep",
            "title": "撰写项目方案",
            "priority": "P1",
            "movable": True,
            "work_mode": "deep",
            "downgrade_allowed": True,
            "start": "2026-09-27T13:00:00+08:00",
        }
    ]
    calendar_source = OfflineCalendar(events)
    body = BodyPlugin()
    body.manifest = registry.get("body")
    plugins = {
        "calendar": CalendarPlugin(calendar_source),
        "task": TaskPlugin(delegates={"task.list": lambda filters: tasks}),
        "body": body,
    }
    flow = TodayFlow(
        CapabilityPlanner(registry),
        Executor(kernel, plugins),
        agent_id="experience_agent",
    )
    response = ExperienceService({FlowName.TODAY: flow}).handle(
        ExperienceRequest(
            text="今天有什么待办",
            correlation_id="corr-e2e-today",
            context={
                "target_date": "2026-09-27",
                "body_snapshot": {
                    "today_energy_context": {
                        "body_battery_score": 18,
                        "sleep_hours": 5.5,
                    }
                },
            },
            dry_run=False,
        )
    )
    public = ExperiencePresenter().present(response)

    assert response.status == "completed"
    assert response.hard_constraints[0].before["start"] == (
        "2026-09-27T14:00:00+08:00"
    )
    assert any(item.reason_code == "high_priority_task" for item in response.suggestions)
    assert response.automatic_adjustments[0].reason_code == (
        "low_energy_deep_work_downgraded"
    )
    assert calendar_source.calls == ["2026-09-27"]
    assert "calendar." not in repr(public)
    assert "task." not in repr(public)
    assert "body." not in repr(public)


def test_low_energy_replans_movable_tasks_but_preserves_commitments():
    flow = AdjustFlow()
    response = ExperienceService({FlowName.ADJUST: flow}).handle(
        ExperienceRequest(
            text="昨晚只睡五小时，帮我调整今天安排",
            correlation_id="corr-e2e-adjust",
            context={
                "energy": {"level": "low", "fresh": True},
                "items": [
                    {
                        "item_id": "meeting-1400",
                        "title": "14:00 固定会议",
                        "item_type": "meeting",
                        "start": "2026-09-27T14:00:00+08:00",
                        "end": "2026-09-27T15:00:00+08:00",
                        "fixed_meeting": True,
                        "external_commitment": True,
                        "movable": False,
                    },
                    {
                        "item_id": "task-deep",
                        "title": "撰写项目方案",
                        "item_type": "task",
                        "start": "2026-09-27T15:00:00+08:00",
                        "end": "2026-09-27T17:00:00+08:00",
                        "work_mode": "deep",
                        "movable": True,
                        "downgrade_allowed": True,
                    },
                ],
                "candidate_slots": [
                    {
                        "start": "2026-09-28T09:00:00+08:00",
                        "end": "2026-09-28T11:00:00+08:00",
                    }
                ],
            },
            dry_run=False,
        )
    )

    meeting = response.hard_constraints[0]
    change = response.automatic_adjustments[0]
    assert meeting.before["start"] == meeting.after["start"]
    assert meeting.before["start"] == "2026-09-27T14:00:00+08:00"
    assert change.reason_code == "low_energy_deep_work_moved"
    assert change.before["start"] != change.after["start"]
    assert change.before != change.after
    assert response.recorded == ()
