from pathlib import Path

import pytest

from agents.information_pipeline import InformationPipeline
from capability_plugins import PluginRegistry, load_manifests
from capability_plugins.body import BodyPlugin
from capability_plugins.calendar import CalendarPlugin
from capability_plugins.information import InformationPlugin, InformationPluginError
from capability_plugins.task import TaskPlugin
from information_system import InformationStore
from orchestration.contracts import CapabilityCall, ExecutionPlan, FlowName, UserIntent
from orchestration.executor import Executor
from runtime_core.action_policy import ActionPolicy
from runtime_core.models import ActionAuthority, PlannedAction
from runtime_core import AgentDefinition, RuntimeKernel


MANIFEST_DIR = Path(__file__).parents[2] / "capability_plugins" / "manifests"


def _core_manifests():
    return {
        manifest.plugin_id: manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id in {"task", "calendar", "body", "information"}
    }


def test_core_adapter_manifests_have_expected_registry_states():
    manifests = _core_manifests()
    registry = PluginRegistry.from_manifests(manifests.values())

    assert set(manifests) == {"task", "calendar", "body", "information"}
    assert registry.explain("task")["status"] == "ready"
    assert registry.explain("calendar")["status"] == "ready"
    assert registry.explain("information")["status"] == "ready"
    assert registry.explain("body")["status"] == "dormant"


@pytest.mark.parametrize("plugin_id", ["task", "calendar", "body", "information"])
def test_core_adapter_manifests_define_policy_for_every_capability(plugin_id):
    manifest = _core_manifests()[plugin_id]

    assert set(manifest.capability_permissions) == set(manifest.provides)
    assert set(manifest.capability_effects) == set(manifest.provides)


@pytest.mark.parametrize("plugin_id", ["task", "calendar", "body", "information"])
def test_core_adapter_permissions_fail_closed_when_agent_has_no_grant(plugin_id):
    manifest = _core_manifests()[plugin_id]
    capability = manifest.provides[0]
    decision = ActionPolicy().evaluate(
        PlannedAction(
            action_id=f"permission-{plugin_id}",
            plugin_id=plugin_id,
            capability=capability,
            authority=ActionAuthority.OBSERVE,
            reversible=True,
            external_effect=False,
            affects_commitment=False,
            risk=manifest.risk_level.value,
            payload_digest="a" * 64,
            required_permissions=manifest.permissions,
        ),
        plugin_permissions=manifest.permissions,
        agent_permissions=(),
        agent_autonomy_level=2,
        known_capabilities=manifest.provides,
    )

    assert decision.allowed is False
    assert decision.reason_code == "agent_permission_denied"


def test_adapter_instances_use_the_same_manifests_as_registry(tmp_path):
    manifests = _core_manifests()
    store = InformationStore(tmp_path / "information.db")
    store.init_schema()

    adapters = {
        "task": TaskPlugin(),
        "calendar": CalendarPlugin(),
        "body": BodyPlugin(),
        "information": InformationPlugin(
            manifests["information"], InformationPipeline(store)
        ),
    }

    assert {plugin_id: adapter.manifest for plugin_id, adapter in adapters.items()} == manifests


def test_plugin_failure_does_not_mutate_registry_or_other_providers(tmp_path):
    manifests = _core_manifests()
    registry = PluginRegistry.from_manifests(manifests.values())
    store = InformationStore(tmp_path / "information.db")
    store.init_schema()
    pipeline = InformationPipeline(store)

    def fail(**kwargs):
        raise RuntimeError("private body text")

    pipeline.ingest = fail
    plugin = InformationPlugin(manifests["information"], pipeline)
    with pytest.raises(InformationPluginError):
        plugin.invoke(
            "information.capture",
            {"source": "manual", "title": "记录", "content": "正文"},
            {},
        )

    assert registry.by_capability("information.capture").plugin_id == "information"
    assert registry.by_capability("task.parse").plugin_id == "task"
    assert registry.explain("calendar")["status"] == "ready"


@pytest.mark.parametrize(
    ("plugin_id", "capability", "agent_permission", "authority"),
    [
        ("task", "task.list", "read_task", ActionAuthority.OBSERVE),
        (
            "task",
            "task.create_proposal",
            "propose_task_change",
            ActionAuthority.AUTONOMOUS,
        ),
        ("calendar", "calendar.list_events", "read_calendar", ActionAuthority.OBSERVE),
        (
            "calendar",
            "calendar.create_proposal",
            "propose_calendar_change",
            ActionAuthority.AUTONOMOUS,
        ),
        (
            "information",
            "information.get",
            "read_information_metadata",
            ActionAuthority.OBSERVE,
        ),
        (
            "information",
            "information.capture",
            "ingest_information",
            ActionAuthority.AUTONOMOUS,
        ),
    ],
)
def test_kernel_uses_capability_scoped_permission_without_sibling_permission(
    tmp_path, plugin_id, capability, agent_permission, authority
):
    manifest = _core_manifests()[plugin_id]
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / f"runtime-{plugin_id}-{capability.replace('.', '-')}",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=PluginRegistry.from_manifests((manifest,)),
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="core_agent",
            name="Core Plugin Agent",
            domain="test",
            autonomy_level=2,
            risk_level="medium",
            permissions=(agent_permission,),
            handler=lambda context: None,
        )
    )

    decision = kernel.authorize_action(
        "core_agent",
        PlannedAction(
            action_id=f"action-{plugin_id}",
            plugin_id=plugin_id,
            capability=capability,
            authority=authority,
            reversible=True,
            external_effect=False,
            affects_commitment=False,
            risk=manifest.risk_level.value,
            payload_digest="b" * 64,
        ),
        correlation_id=f"corr-{plugin_id}",
    )

    assert decision.allowed is True
    assert decision.approval_required is False


def test_executor_marks_missing_calendar_delegate_as_failed(tmp_path):
    manifest = _core_manifests()["calendar"]
    registry = PluginRegistry.from_manifests((manifest,))
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "calendar-runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
        default_network_mode="ASSIST",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="calendar_agent",
            name="Calendar Agent",
            domain="calendar",
            autonomy_level=2,
            risk_level="medium",
            permissions=("read_calendar",),
            handler=lambda context: None,
        )
    )
    plan = ExecutionPlan(
        flow=FlowName.TODAY,
        intent=UserIntent(
            flow=FlowName.TODAY,
            text="查看今天日程",
            confidence=1.0,
            evidence=("test",),
            correlation_id="corr-calendar-missing",
        ),
        steps=(
            CapabilityCall(
                "calendar-read",
                "calendar",
                "calendar.list_events",
                {"target_date": "2026-09-26"},
            ),
        ),
        assumptions=(),
        requires_confirmation=False,
    )

    result = Executor(kernel, {"calendar": CalendarPlugin()}).execute(
        plan,
        agent_id="calendar_agent",
        dry_run=False,
    )

    assert result.status == "failed"
    assert result.steps[0].status == "failed"
    assert result.steps[0].error_code == "calendar_module_unavailable"


def test_executor_requires_approval_for_explicit_calendar_commitment(tmp_path):
    manifest = _core_manifests()["calendar"]
    registry = PluginRegistry.from_manifests((manifest,))
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "calendar-commitment-runtime",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="calendar_agent",
            name="Calendar Agent",
            domain="calendar",
            autonomy_level=2,
            risk_level="medium",
            permissions=("propose_calendar_change",),
            handler=lambda context: None,
        )
    )
    plan = ExecutionPlan(
        flow=FlowName.ADJUST,
        intent=UserIntent(
            flow=FlowName.ADJUST,
            text="创建固定会议提案",
            confidence=1.0,
            evidence=("test",),
            correlation_id="corr-calendar-commitment",
        ),
        steps=(
            CapabilityCall(
                "calendar-proposal",
                "calendar",
                "calendar.create_proposal",
                {
                    "summary": "固定会议",
                    "start_iso": "2026-09-28T14:00:00+08:00",
                    "end_iso": "2026-09-28T15:00:00+08:00",
                    "fixed_meeting": True,
                },
            ),
        ),
        assumptions=(),
        requires_confirmation=False,
    )

    result = Executor(kernel, {"calendar": CalendarPlugin()}).execute(
        plan,
        agent_id="calendar_agent",
        dry_run=False,
    )

    assert result.status == "blocked"
    assert result.steps[0].status == "blocked"
    assert result.steps[0].decision.approval_required is True
    assert (
        result.steps[0].decision.reason_code
        == "approval_required_external_commitment"
    )
