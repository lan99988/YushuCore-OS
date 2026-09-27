from __future__ import annotations

import pytest
from types import SimpleNamespace

from capability_plugins.contracts import (
    ActivationState,
    Availability,
    PluginManifest,
    RiskLevel,
)
from capability_plugins.registry import PluginRegistry
from orchestration.planner import CapabilityPlanner, CapabilityRequest, PlanningResult


def _manifest(
    plugin_id: str,
    *capabilities: str,
    activation_mode: str = "always",
    activation_state: ActivationState = ActivationState.ACTIVE,
    availability: Availability = Availability.INSTALLED,
    enabled: bool = True,
    dependencies: tuple[str, ...] = (),
    capability_priorities: dict[str, int] | None = None,
    capability_priority_reasons: dict[str, str] | None = None,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        name=f"{plugin_id.title()} Plugin",
        version="1.0.0",
        purpose=f"Provides {plugin_id} capabilities for planner tests",
        domain=plugin_id,
        provides=tuple(capabilities),
        reads=(),
        writes=(),
        dependencies=dependencies,
        permissions=(),
        risk_level=RiskLevel.LOW,
        activation_mode=activation_mode,
        availability=availability,
        enabled=enabled,
        activation_state=activation_state,
        capability_priorities=capability_priorities or {},
        capability_priority_reasons=capability_priority_reasons or {},
    )


def _intent():
    return SimpleNamespace(flow="plan")


def _contract_intent():
    from orchestration.contracts import FlowName, UserIntent

    return UserIntent(
        flow=FlowName.PLAN,
        text="Plan the task",
        confidence=0.95,
        evidence=("explicit planning request",),
        correlation_id="corr-planner-1",
    )


def test_planner_uses_only_registered_ready_capabilities_and_is_deterministic():
    from orchestration.contracts import CapabilityCall, ExecutionPlan, FlowName

    registry = PluginRegistry.from_manifests(
        (
            _manifest(
                "task",
                "task.read",
                "task.update",
                capability_priorities={"task.read": 1},
                capability_priority_reasons={"task.read": "ready provider"},
            ),
            _manifest(
                "dormant_fallback",
                "task.read",
                activation_mode="on_demand",
                activation_state=ActivationState.DORMANT,
                capability_priorities={"task.read": 100},
                capability_priority_reasons={"task.read": "preferred when active"},
            ),
        )
    )
    planner = CapabilityPlanner(registry)
    requests = (
        CapabilityRequest("write", "task.update", {"title": "Plan"}, ("read",)),
        CapabilityRequest("read", "task.read", {"query": "today"}),
    )

    intent = _contract_intent()
    first = planner.plan(intent, requests, assumptions=("use local task data",))
    second = planner.plan(intent, requests, assumptions=("use local task data",))

    assert isinstance(first, PlanningResult)
    assert first == second
    assert first.gaps == ()
    assert isinstance(first.plan, ExecutionPlan)
    assert first.plan.flow is FlowName.PLAN
    assert first.plan.intent == intent
    assert tuple(step.step_id for step in first.plan.steps) == ("read", "write")
    assert all(isinstance(step, CapabilityCall) for step in first.plan.steps)
    assert {step.plugin_id for step in first.plan.steps} == {"task"}
    assert first.plan.steps[1].depends_on == ("read",)
    assert first.plan.assumptions == ("use local task data",)
    assert first.plan.requires_confirmation is False


def test_planner_emits_plan_created_metadata_without_plan_payload():
    from runtime_core.events import EventBus

    bus = EventBus()
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests((_manifest("task", "task.read"),)),
        events=bus,
    )

    result = planner.plan(
        _contract_intent(),
        (CapabilityRequest("read", "task.read", {"query": "PRIVATE-PLAN-QUERY"}),),
    )

    assert result.plan is not None
    assert bus.history == [
        {
            "event": "plan_created",
            "flow": "plan",
            "correlation_id": "corr-planner-1",
            "step_count": 1,
        }
    ]
    assert "PRIVATE-PLAN-QUERY" not in repr(bus.history)


def test_planner_returns_explicit_gap_for_unregistered_capability():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests((_manifest("task", "task.read"),))
    )

    result = planner.plan(
        _intent(),
        (CapabilityRequest("calendar", "calendar.create", {"title": "Review"}),),
    )

    assert result.plan is None
    assert len(result.gaps) == 1
    assert result.gaps[0].step_id == "calendar"
    assert result.gaps[0].capability == "calendar.create"
    assert result.gaps[0].reason_code == "unknown_capability"
    assert result.gaps[0].explanation.strip()


def test_planner_returns_explicit_gap_for_registered_but_unready_provider():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests(
            (
                _manifest(
                    "calendar",
                    "calendar.create",
                    activation_mode="on_demand",
                    activation_state=ActivationState.DORMANT,
                ),
            )
        )
    )

    result = planner.plan(
        _intent(),
        (CapabilityRequest("calendar", "calendar.create", {"title": "Review"}),),
    )

    assert result.plan is None
    assert result.gaps[0].reason_code == "provider_not_ready"


def test_planner_marks_requested_on_demand_provider_without_mutating_registry():
    registry = PluginRegistry.from_manifests(
        (
            _manifest(
                "calendar",
                "calendar.create",
                activation_mode="on_demand",
                activation_state=ActivationState.DORMANT,
            ),
        )
    )
    planner = CapabilityPlanner(
        registry,
        activate_on_demand=True,
    )

    result = planner.plan(
        _contract_intent(),
        (CapabilityRequest("calendar", "calendar.create", {"title": "Review"}),),
    )

    assert result.gaps == ()
    assert result.plan.steps[0].plugin_id == "calendar"
    assert result.plan.on_demand_plugins == ("calendar",)
    assert registry.get("calendar").activation_state is ActivationState.DORMANT
    assert all(event["action"] != "state_changed" for event in registry.audit_events)


def test_planner_returns_gap_for_unknown_step_dependency():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests((_manifest("task", "task.read"),))
    )

    result = planner.plan(
        _intent(),
        (
            CapabilityRequest("read", "task.read", {}, ("missing-step",)),
        ),
    )

    assert result.plan is None
    assert result.gaps[0].reason_code == "unknown_dependency"
    assert "missing-step" in result.gaps[0].explanation


def test_planner_returns_gap_for_dependency_cycle():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests(
            (_manifest("task", "task.read", "task.update"),)
        )
    )

    result = planner.plan(
        _intent(),
        (
            CapabilityRequest("read", "task.read", {}, ("write",)),
            CapabilityRequest("write", "task.update", {}, ("read",)),
        ),
    )

    assert result.plan is None
    assert result.gaps
    assert all(gap.reason_code == "dependency_cycle" for gap in result.gaps)


def test_planner_distinguishes_cycle_members_from_downstream_blocked_steps():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests(
            (_manifest("task", "task.read", "task.update", "task.summarize"),)
        )
    )

    result = planner.plan(
        _intent(),
        (
            CapabilityRequest("a", "task.read", {}, ("b",)),
            CapabilityRequest("b", "task.update", {}, ("a",)),
            CapabilityRequest("c", "task.summarize", {}, ("b",)),
        ),
    )

    gaps = {gap.step_id: gap.reason_code for gap in result.gaps}
    assert result.plan is None
    assert gaps == {
        "a": "dependency_cycle",
        "b": "dependency_cycle",
        "c": "dependency_blocked_by_cycle",
    }


def test_planner_cycle_detection_includes_all_members_of_strong_component():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests(
            (_manifest("task", "task.a", "task.b", "task.c"),)
        )
    )

    result = planner.plan(
        _intent(),
        (
            CapabilityRequest("a", "task.a", {}, ("b", "c")),
            CapabilityRequest("b", "task.b", {}, ("a",)),
            CapabilityRequest("c", "task.c", {}, ("b",)),
        ),
    )

    assert result.plan is None
    assert {gap.step_id: gap.reason_code for gap in result.gaps} == {
        "a": "dependency_cycle",
        "b": "dependency_cycle",
        "c": "dependency_cycle",
    }


def test_planner_rejects_duplicate_step_ids():
    planner = CapabilityPlanner(
        PluginRegistry.from_manifests((_manifest("task", "task.read"),))
    )

    with pytest.raises(ValueError, match="duplicate step_id"):
        planner.plan(
            _intent(),
            (
                CapabilityRequest("read", "task.read", {}),
                CapabilityRequest("read", "task.read", {"query": "again"}),
            ),
        )
