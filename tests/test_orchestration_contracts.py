from dataclasses import FrozenInstanceError

import pytest

from orchestration.contracts import (
    CapabilityCall,
    ExecutionPlan,
    FlowName,
    UserIntent,
)


def _intent(flow=FlowName.PLAN):
    return UserIntent(
        flow=flow,
        text="规划本周项目",
        confidence=0.95,
        evidence=("规划",),
        correlation_id="corr-1",
    )


def _call(step_id="step-1", *, depends_on=(), payload=None):
    return CapabilityCall(
        step_id=step_id,
        plugin_id="project",
        capability="project.plan",
        payload={} if payload is None else payload,
        depends_on=depends_on,
    )


def test_flow_name_has_exactly_the_six_supported_logic_chains():
    assert {flow.value for flow in FlowName} == {
        "capture",
        "plan",
        "today",
        "adjust",
        "review",
        "explore",
    }


def test_orchestration_package_exports_wp3_public_api():
    import orchestration

    assert orchestration.FlowName is FlowName
    assert orchestration.UserIntent is UserIntent
    assert orchestration.CapabilityCall is CapabilityCall
    assert orchestration.ExecutionPlan is ExecutionPlan
    assert orchestration.IntentRouter.__name__ == "IntentRouter"
    assert orchestration.CapabilityPlanner.__name__ == "CapabilityPlanner"
    assert orchestration.Executor.__name__ == "Executor"


def test_user_intent_is_frozen_and_rejects_invalid_confidence():
    intent = _intent()

    with pytest.raises(FrozenInstanceError):
        intent.text = "changed"
    with pytest.raises(ValueError, match="confidence"):
        UserIntent(
            flow=FlowName.PLAN,
            text="plan",
            confidence=float("nan"),
            evidence=("plan",),
            correlation_id="corr-1",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"flow": "plan"},
        {"text": "   "},
        {"confidence": 1.01},
        {"confidence": True},
        {"evidence": ["plan"]},
        {"correlation_id": "not a controlled id"},
    ],
)
def test_user_intent_rejects_invalid_fields(overrides):
    values = {
        "flow": FlowName.PLAN,
        "text": "规划本周项目",
        "confidence": 0.95,
        "evidence": ("规划",),
        "correlation_id": "corr-1",
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError)):
        UserIntent(**values)


def test_capability_call_takes_a_defensive_payload_snapshot():
    original = {"filters": {"domain": "project"}, "labels": ["active"]}
    call = _call(payload=original)

    original["filters"]["domain"] = "body"
    original["labels"].append("private")

    assert call.payload == {"filters": {"domain": "project"}, "labels": ["active"]}


def test_capability_call_payload_snapshot_is_recursively_immutable():
    call = _call(payload={"filters": {"domain": "project"}, "labels": ["active"]})

    with pytest.raises(TypeError):
        call.payload["new"] = "value"
    with pytest.raises(TypeError):
        call.payload["filters"]["domain"] = "body"
    with pytest.raises(TypeError):
        call.payload["labels"].append("private")


def test_capability_call_payload_cannot_be_mutated_through_builtin_base_methods():
    call = _call(
        payload={
            "affects_commitment": True,
            "nested": {"items": ["original"]},
        }
    )

    with pytest.raises(TypeError):
        dict.__setitem__(call.payload, "affects_commitment", False)
    with pytest.raises(TypeError):
        dict.__setitem__(call.payload["nested"], "new", "value")
    with pytest.raises(TypeError):
        list.append(call.payload["nested"]["items"], "mutated")
    with pytest.raises((AttributeError, TypeError)):
        call.payload._data["affects_commitment"] = False
    with pytest.raises((AttributeError, TypeError)):
        call.payload._data = {"affects_commitment": False}
    with pytest.raises((AttributeError, TypeError)):
        call.payload["nested"]["items"]._items = ("mutated",)
    assert call.payload["affects_commitment"] is True


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_capability_call_rejects_non_finite_payload_numbers(non_finite):
    with pytest.raises(ValueError, match="finite"):
        _call(payload={"score": non_finite})


@pytest.mark.parametrize(
    "overrides",
    [
        {"step_id": "Step 1"},
        {"plugin_id": "../project"},
        {"capability": ""},
        {"payload": []},
        {"depends_on": ["step-0"]},
        {"depends_on": ("step-1",)},
    ],
)
def test_capability_call_rejects_invalid_fields(overrides):
    values = {
        "step_id": "step-1",
        "plugin_id": "project",
        "capability": "project.plan",
        "payload": {},
        "depends_on": (),
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError)):
        CapabilityCall(**values)


def test_execution_plan_requires_matching_flow_and_unique_steps():
    with pytest.raises(ValueError, match="intent.flow"):
        ExecutionPlan(
            flow=FlowName.CAPTURE,
            intent=_intent(FlowName.PLAN),
            steps=(_call(),),
            assumptions=(),
            requires_confirmation=False,
        )

    with pytest.raises(ValueError, match="unique"):
        ExecutionPlan(
            flow=FlowName.PLAN,
            intent=_intent(),
            steps=(_call("step-1"), _call("step-1")),
            assumptions=(),
            requires_confirmation=False,
        )


def test_execution_plan_requires_valid_acyclic_dependencies():
    with pytest.raises(ValueError, match="unknown dependency"):
        ExecutionPlan(
            flow=FlowName.PLAN,
            intent=_intent(),
            steps=(_call("step-1", depends_on=("missing",)),),
            assumptions=(),
            requires_confirmation=False,
        )

    with pytest.raises(ValueError, match="cycle"):
        ExecutionPlan(
            flow=FlowName.PLAN,
            intent=_intent(),
            steps=(
                _call("step-1", depends_on=("step-2",)),
                _call("step-2", depends_on=("step-1",)),
            ),
            assumptions=(),
            requires_confirmation=False,
        )


def test_execution_plan_rejects_mutable_or_malformed_collections():
    with pytest.raises((TypeError, ValueError), match="steps"):
        ExecutionPlan(
            flow=FlowName.PLAN,
            intent=_intent(),
            steps=[_call()],
            assumptions=(),
            requires_confirmation=False,
        )

    with pytest.raises((TypeError, ValueError), match="requires_confirmation"):
        ExecutionPlan(
            flow=FlowName.PLAN,
            intent=_intent(),
            steps=(_call(),),
            assumptions=(),
            requires_confirmation=1,
        )
