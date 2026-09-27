from __future__ import annotations

import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from capability_plugins.contracts import (
    ActivationState,
    Availability,
    PluginManifest,
    RiskLevel,
)
from capability_plugins.registry import PluginRegistry
from orchestration.contracts import CapabilityCall, ExecutionPlan, FlowName, UserIntent
from orchestration.intent_router import IntentRouter
from orchestration.planner import CapabilityPlanner, CapabilityRequest
from runtime_core import AgentDefinition, RuntimeKernel
from runtime_core.audit import canonical_payload_digest


def _executor_api():
    try:
        spec = importlib.util.find_spec("orchestration.executor")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "orchestration.executor is required to execute plans"
    return importlib.import_module("orchestration.executor")


class RecordingPlugin:
    def __init__(self, manifest: PluginManifest, *, fail: bool = False) -> None:
        self.manifest = manifest
        self.fail = fail
        self.calls: list[tuple[str, dict, object]] = []

    def invoke(self, capability: str, payload: dict, context: object):
        self.calls.append((capability, payload, context))
        if self.fail:
            raise RuntimeError("private plugin failure detail")
        return {"handled": capability}


class RecoverablePlugin(RecordingPlugin):
    def __init__(self, manifest: PluginManifest, *, fail: bool = False) -> None:
        super().__init__(manifest, fail=fail)
        self.rollbacks = []

    def rollback(self, capability: str, payload: dict, context: object, result: object):
        self.rollbacks.append((capability, payload, context, result))


def _manifest(
    plugin_id: str,
    *capabilities: str,
    permissions: tuple[str, ...] | None = None,
    writes: tuple[str, ...] = (),
    risk: RiskLevel = RiskLevel.LOW,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        name=f"{plugin_id} plugin",
        version="1.0.0",
        purpose="executor test",
        domain="test",
        provides=tuple(capabilities),
        reads=("test.records",),
        writes=writes,
        dependencies=(),
        permissions=permissions or tuple(capabilities),
        risk_level=risk,
        activation_mode="always",
        availability=Availability.INSTALLED,
        enabled=True,
        activation_state=ActivationState.ACTIVE,
    )


def _kernel(tmp_path: Path, manifests: tuple[PluginManifest, ...]) -> RuntimeKernel:
    permissions = tuple(sorted({p for manifest in manifests for p in manifest.permissions}))
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime_state",
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=PluginRegistry.from_manifests(manifests),
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="test_agent",
            name="Executor Test Agent",
            domain="test",
            autonomy_level=2,
            risk_level="low",
            permissions=permissions,
            handler=lambda context: None,
        )
    )
    return kernel


def _plan(*steps: CapabilityCall, requires_confirmation: bool = False) -> ExecutionPlan:
    return ExecutionPlan(
        flow=FlowName.TODAY,
        intent=UserIntent(
            flow=FlowName.TODAY,
            text="run executor test",
            confidence=1.0,
            evidence=("executor test input",),
            correlation_id="corr-executor-1",
        ),
        steps=tuple(steps),
        assumptions=(),
        requires_confirmation=requires_confirmation,
    )


def test_executor_dry_run_never_invokes_plugin_and_returns_policy_and_expectations(tmp_path):
    manifest = _manifest(
        "reader",
        "records.read",
        permissions=("records.read",),
    )
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(
        CapabilityCall("read", "reader", "records.read", {"query": "today"})
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=True)

    assert result.status == "dry_run"
    assert result.plan is plan
    assert result.steps[0].decision.allowed is True
    assert result.steps[0].status == "planned"
    assert result.expected_changes == ()
    assert plugin.calls == []


def test_executor_blocks_unapproved_external_write_without_calling_plugin(tmp_path):
    manifest = _manifest(
        "calendar",
        "calendar.create_event",
        permissions=("calendar.write",),
        writes=("external.calendar",),
    )
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"calendar": plugin})
    plan = _plan(
        CapabilityCall(
            "create-event",
            "calendar",
            "calendar.create_event",
            {"title": "private title"},
        )
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "blocked"
    assert result.steps[0].decision.approval_required is True
    assert result.steps[0].status == "blocked"
    assert result.expected_changes == ("calendar:calendar.create_event",)
    assert plugin.calls == []


def test_executor_stops_dependents_continues_independent_read_only_and_marks_partial(tmp_path):
    failing_manifest = _manifest(
        "failing_reader", "records.read_first", permissions=("records.read_first",)
    )
    dependent_manifest = _manifest(
        "dependent_reader", "records.read_dependent", permissions=("records.read_dependent",)
    )
    independent_manifest = _manifest(
        "independent_reader", "records.read_independent", permissions=("records.read_independent",)
    )
    failing = RecordingPlugin(failing_manifest, fail=True)
    dependent = RecordingPlugin(dependent_manifest)
    independent = RecordingPlugin(independent_manifest)
    kernel = _kernel(
        tmp_path,
        (failing_manifest, dependent_manifest, independent_manifest),
    )
    executor = _executor_api().Executor(
        kernel,
        {
            "failing_reader": failing,
            "dependent_reader": dependent,
            "independent_reader": independent,
        },
    )
    plan = _plan(
        CapabilityCall("first", "failing_reader", "records.read_first", {}),
        CapabilityCall(
            "dependent",
            "dependent_reader",
            "records.read_dependent",
            {},
            depends_on=("first",),
        ),
        CapabilityCall(
            "independent",
            "independent_reader",
            "records.read_independent",
            {},
        ),
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    statuses = {step.step_id: step.status for step in result.steps}
    assert result.status == "partial"
    assert statuses == {
        "first": "failed",
        "dependent": "skipped",
        "independent": "completed",
    }
    assert [call[0] for call in failing.calls] == ["records.read_first"]
    assert dependent.calls == []
    assert [call[0] for call in independent.calls] == ["records.read_independent"]
    assert "private plugin failure detail" not in str(result.steps)


def test_executor_emits_policy_and_plugin_lifecycle_metadata(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(
        CapabilityCall(
            "read",
            "reader",
            "records.read",
            {"query": "PRIVATE-PLUGIN-QUERY"},
        )
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "completed"
    events = kernel.events.history
    names = [event["event"] for event in events]
    assert "policy_allowed" in names
    assert "plugin_started" in names
    assert "plugin_completed" in names
    assert all(event["correlation_id"] == "corr-executor-1" for event in events)
    assert "PRIVATE-PLUGIN-QUERY" not in repr(events)


def test_executor_fails_closed_when_audit_sink_fails(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})

    def fail_audit(_record):
        raise OSError("private audit sink detail")

    kernel.audit.write = fail_audit
    plan = _plan(CapabilityCall("read", "reader", "records.read", {}))

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "blocked"
    assert result.steps[0].error_code == "authorization_failed"
    assert plugin.calls == []
    assert "private audit sink detail" not in repr(kernel.events.history)


def test_executor_only_reports_rollback_completed_after_compensation_returns(tmp_path):
    writer_manifest = _manifest(
        "writer", "records.write", permissions=("records.write",)
    )
    writer_manifest = replace(
        writer_manifest,
        capability_effects={"records.write": "internal_write"},
    )
    failing_manifest = _manifest(
        "failing_reader", "records.read", permissions=("records.read",)
    )
    writer = RecoverablePlugin(writer_manifest)
    failing = RecordingPlugin(failing_manifest, fail=True)
    kernel = _kernel(tmp_path, (writer_manifest, failing_manifest))
    executor = _executor_api().Executor(
        kernel, {"writer": writer, "failing_reader": failing}
    )
    plan = _plan(
        CapabilityCall("write", "writer", "records.write", {"value": "safe"}),
        CapabilityCall("read", "failing_reader", "records.read", {}),
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "partial"
    assert len(writer.rollbacks) == 1
    rollback_events = [
        event["event"]
        for event in kernel.events.history
        if event["event"].startswith("rollback_")
    ]
    assert rollback_events == ["rollback_started", "rollback_completed"]
    completed = next(
        event
        for event in kernel.events.history
        if event["event"] == "rollback_completed"
    )
    assert completed["status"] == "completed"


def test_executor_rejects_dependency_cycle_before_invoking_plugins(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(
        CapabilityCall("first", "reader", "records.read", {}),
        CapabilityCall("second", "reader", "records.read", {}, depends_on=("first",)),
    )
    # Simulate a corrupted/stale plan crossing the public API boundary; the
    # executor still must refuse it before invoking any injected plugin.
    object.__setattr__(plan.steps[0], "depends_on", ("second",))

    with pytest.raises(ValueError, match="dependency cycle"):
        executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert plugin.calls == []


def test_executor_requires_explicit_registered_plugin_executor(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {})
    plan = _plan(CapabilityCall("read", "reader", "records.read", {}))

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "blocked"
    assert result.steps[0].status == "blocked"
    assert result.steps[0].error_code == "plugin_executor_missing"


def test_executor_rejects_forged_planned_provider_before_authorization(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(CapabilityCall("read", "forged", "records.read", {}))

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "blocked"
    assert result.steps[0].error_code == "planned_provider_mismatch"
    assert plugin.calls == []
    assert not (tmp_path / "runtime_state" / "audit.jsonl").exists()


def test_router_planner_executor_dry_run_end_to_end_has_no_plugin_side_effects(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    intent = IntentRouter().route("今天有什么待办", correlation_id="corr-e2e-dry-run")
    planning = CapabilityPlanner(kernel.plugin_registry).plan(
        intent,
        (CapabilityRequest("read", "records.read", {"scope": "today"}),),
    )

    result = _executor_api().Executor(kernel, {"reader": plugin}).execute(
        planning.plan,
        agent_id="test_agent",
        dry_run=True,
    )

    assert planning.gaps == ()
    assert planning.plan.flow is FlowName.TODAY
    assert result.status == "dry_run"
    assert result.steps[0].status == "planned"
    assert result.steps[0].decision.allowed is True
    assert plugin.calls == []


def test_executor_rejects_injected_plugin_with_manifest_different_from_registry(tmp_path):
    registered = _manifest("reader", "records.read", permissions=("records.read",))
    injected_manifest = _manifest(
        "reader",
        "records.read",
        permissions=("records.read",),
        writes=("external.records",),
    )
    plugin = RecordingPlugin(injected_manifest)
    kernel = _kernel(tmp_path, (registered,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(CapabilityCall("read", "reader", "records.read", {}))

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "blocked"
    assert result.steps[0].error_code == "plugin_manifest_mismatch"
    assert plugin.calls == []


def test_executor_accepts_registry_owned_lifecycle_state_change(tmp_path):
    dormant = replace(
        _manifest("reader", "records.read", permissions=("records.read",)),
        activation_mode="on_demand",
        activation_state=ActivationState.DORMANT,
    )
    active = replace(dormant, activation_state=ActivationState.ACTIVE)
    plugin = RecordingPlugin(dormant)
    kernel = _kernel(tmp_path, (active,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(CapabilityCall("read", "reader", "records.read", {}))

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "completed"
    assert result.steps[0].status == "completed"
    assert len(plugin.calls) == 1


def test_executor_invokes_plugin_with_mutable_copy_of_nonempty_frozen_payload(tmp_path):
    manifest = _manifest("reader", "records.read", permissions=("records.read",))
    plugin = RecordingPlugin(manifest)
    kernel = _kernel(tmp_path, (manifest,))
    executor = _executor_api().Executor(kernel, {"reader": plugin})
    plan = _plan(
        CapabilityCall(
            "read",
            "reader",
            "records.read",
            {"nested": {"items": ["a"]}},
        )
    )

    result = executor.execute(plan, agent_id="test_agent", dry_run=False)

    assert result.status == "completed"
    invoked_payload = plugin.calls[0][1]
    invoked_payload["nested"]["items"].append("b")
    assert invoked_payload == {"nested": {"items": ["a", "b"]}}
    assert plan.steps[0].payload == {"nested": {"items": ["a"]}}
