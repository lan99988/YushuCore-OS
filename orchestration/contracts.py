from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any


class _FrozenMapping(tuple, Mapping[str, Any]):
    __slots__ = ()

    def __new__(cls, data: dict[str, Any]):
        return tuple.__new__(cls, tuple(data.items()))

    def __getitem__(self, key: str) -> Any:
        for candidate, value in tuple.__iter__(self):
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in tuple.__iter__(self))

    def __len__(self) -> int:
        return tuple.__len__(self)

    def __repr__(self) -> str:
        return repr(dict(self.items()))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self.items()) == dict(other.items())


class _FrozenSequence(tuple):
    __slots__ = ()

    def __new__(cls, items: tuple[Any, ...]):
        return tuple.__new__(cls, items)

    def __repr__(self) -> str:
        return repr(list(tuple.__iter__(self)))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Sequence)
            and not isinstance(other, (str, bytes, bytearray))
            and list(tuple.__iter__(self)) == list(other)
        )

    def append(self, value: Any) -> None:
        del value
        raise TypeError("capability payload snapshot is immutable")


def _freeze_payload(value: Any) -> Any:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("payload keys must be strings")
        return _FrozenMapping(
            {key: _freeze_payload(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _FrozenSequence(tuple(_freeze_payload(item) for item in value))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("payload numbers must be finite")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError("payload must contain only JSON-compatible values")


class FlowName(str, Enum):
    CAPTURE = "capture"
    PLAN = "plan"
    TODAY = "today"
    ADJUST = "adjust"
    REVIEW = "review"
    EXPLORE = "explore"


_CONTROLLED_ID = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _require_id(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not _CONTROLLED_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a controlled identifier")


def _require_text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_text_tuple(field_name: str, value: object) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain only non-empty strings")


def _require_confidence(value: object) -> None:
    if type(value) is not float or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be a finite float between 0 and 1")


@dataclass(frozen=True)
class UserIntent:
    flow: FlowName
    text: str
    confidence: float
    evidence: tuple[str, ...]
    correlation_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.flow, FlowName):
            raise TypeError("flow must be a FlowName")
        _require_text("text", self.text)
        _require_confidence(self.confidence)
        _require_text_tuple("evidence", self.evidence)
        if not isinstance(self.correlation_id, str) or not _CORRELATION_ID.fullmatch(
            self.correlation_id
        ):
            raise ValueError("correlation_id must be a controlled identifier")


@dataclass(frozen=True)
class CapabilityCall:
    step_id: str
    plugin_id: str
    capability: str
    payload: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id("step_id", self.step_id)
        _require_id("plugin_id", self.plugin_id)
        _require_id("capability", self.capability)
        if type(self.payload) is not dict:
            raise TypeError("payload must be a dict")
        payload_snapshot = _freeze_payload(self.payload)
        object.__setattr__(self, "payload", payload_snapshot)
        _require_text_tuple("depends_on", self.depends_on)
        for dependency in self.depends_on:
            _require_id("depends_on item", dependency)
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on must not contain duplicates")
        if self.step_id in self.depends_on:
            raise ValueError("a step cannot depend on itself")


@dataclass(frozen=True)
class ExecutionPlan:
    flow: FlowName
    intent: UserIntent
    steps: tuple[CapabilityCall, ...]
    assumptions: tuple[str, ...]
    requires_confirmation: bool
    on_demand_plugins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.flow, FlowName):
            raise TypeError("flow must be a FlowName")
        if not isinstance(self.intent, UserIntent):
            raise TypeError("intent must be a UserIntent")
        if self.intent.flow is not self.flow:
            raise ValueError("intent.flow must match plan flow")
        if type(self.steps) is not tuple or any(
            not isinstance(step, CapabilityCall) for step in self.steps
        ):
            raise TypeError("steps must be a tuple of CapabilityCall values")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        known_ids = set(step_ids)
        for step in self.steps:
            missing = set(step.depends_on) - known_ids
            if missing:
                raise ValueError(
                    "unknown dependency step_id: " + ", ".join(sorted(missing))
                )
        _validate_acyclic(self.steps)
        _require_text_tuple("assumptions", self.assumptions)
        if type(self.requires_confirmation) is not bool:
            raise TypeError("requires_confirmation must be a bool")
        _require_text_tuple("on_demand_plugins", self.on_demand_plugins)
        for plugin_id in self.on_demand_plugins:
            _require_id("on_demand_plugins item", plugin_id)
        if len(self.on_demand_plugins) != len(set(self.on_demand_plugins)):
            raise ValueError("on_demand_plugins must not contain duplicates")
        planned_plugin_ids = {step.plugin_id for step in self.steps}
        unknown_plugins = set(self.on_demand_plugins) - planned_plugin_ids
        if unknown_plugins:
            raise ValueError(
                "on_demand_plugins must be referenced by plan steps: "
                + ", ".join(sorted(unknown_plugins))
            )


def _validate_acyclic(steps: tuple[CapabilityCall, ...]) -> None:
    dependencies = {step.step_id: set(step.depends_on) for step in steps}
    complete: set[str] = set()
    while dependencies:
        ready = {step_id for step_id, deps in dependencies.items() if not deps}
        if not ready:
            raise ValueError("execution plan dependency cycle")
        complete.update(ready)
        for step_id in ready:
            dependencies.pop(step_id)
        for deps in dependencies.values():
            deps.difference_update(complete)


@dataclass(frozen=True)
class ClarificationRequest:
    text: str
    question: str
    reason_code: str
    confidence: float
    high_risk: bool
    correlation_id: str
    candidate_flow: FlowName | None = None

    def __post_init__(self) -> None:
        _require_text("text", self.text)
        _require_text("question", self.question)
        _require_id("reason_code", self.reason_code)
        _require_confidence(self.confidence)
        if type(self.high_risk) is not bool:
            raise TypeError("high_risk must be a bool")
        if not isinstance(self.correlation_id, str) or not _CORRELATION_ID.fullmatch(
            self.correlation_id
        ):
            raise ValueError("correlation_id must be a controlled identifier")
        if self.candidate_flow is not None and not isinstance(
            self.candidate_flow, FlowName
        ):
            raise TypeError("candidate_flow must be a FlowName or None")
