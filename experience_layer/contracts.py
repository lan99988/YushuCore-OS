from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from orchestration import FlowName


_CONTROLLED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_STATUSES = frozenset(
    {"completed", "partial", "blocked", "needs_clarification", "unsupported"}
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("snapshot keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("snapshot numbers must be finite")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError("snapshot must contain only JSON-compatible values")


def _require_text(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_id(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not _CONTROLLED_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a controlled identifier")


@dataclass(frozen=True)
class ExperienceRequest:
    text: str
    correlation_id: str
    structured_flow: FlowName | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    diagnostic: bool = False

    def __post_init__(self) -> None:
        _require_text("text", self.text)
        _require_id("correlation_id", self.correlation_id)
        if self.structured_flow is not None and not isinstance(
            self.structured_flow, FlowName
        ):
            raise TypeError("structured_flow must be a FlowName or None")
        if not isinstance(self.context, Mapping):
            raise TypeError("context must be a mapping")
        if type(self.dry_run) is not bool:
            raise TypeError("dry_run must be a bool")
        if type(self.diagnostic) is not bool:
            raise TypeError("diagnostic must be a bool")
        object.__setattr__(self, "context", _freeze(self.context))


@dataclass(frozen=True)
class ExperienceItem:
    item_id: str
    title: str
    reason_code: str
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None
    requires_confirmation: bool = False
    rule_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        _require_id("item_id", self.item_id)
        _require_text("title", self.title)
        _require_id("reason_code", self.reason_code)
        for field_name in ("before", "after"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise TypeError(f"{field_name} must be a mapping or None")
                object.__setattr__(self, field_name, _freeze(value))
        if type(self.requires_confirmation) is not bool:
            raise TypeError("requires_confirmation must be a bool")
        if self.rule_id is not None:
            _require_id("rule_id", self.rule_id)
        if type(self.evidence_refs) is not tuple:
            raise TypeError("evidence_refs must be a tuple")
        for evidence_ref in self.evidence_refs:
            _require_id("evidence_ref", evidence_ref)
        if self.rule_id is None and self.evidence_refs:
            raise ValueError("evidence_refs require a rule_id")
        if self.confidence is not None and (
            type(self.confidence) not in {int, float}
            or not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confidence must be between 0 and 1")
        if self.rule_id is None and self.confidence is not None:
            raise ValueError("confidence requires a rule_id")


@dataclass(frozen=True)
class ExperienceResponse:
    flow: FlowName | None
    status: str
    understood: tuple[ExperienceItem, ...] = ()
    recorded: tuple[ExperienceItem, ...] = ()
    hard_constraints: tuple[ExperienceItem, ...] = ()
    suggestions: tuple[ExperienceItem, ...] = ()
    automatic_adjustments: tuple[ExperienceItem, ...] = ()
    confirmations: tuple[ExperienceItem, ...] = ()
    uncertainties: tuple[ExperienceItem, ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.flow is not None and not isinstance(self.flow, FlowName):
            raise TypeError("flow must be a FlowName or None")
        if self.status not in _STATUSES:
            raise ValueError("status is unsupported")
        for field_name in (
            "understood",
            "recorded",
            "hard_constraints",
            "suggestions",
            "automatic_adjustments",
            "confirmations",
            "uncertainties",
        ):
            value = getattr(self, field_name)
            if type(value) is not tuple or any(
                not isinstance(item, ExperienceItem) for item in value
            ):
                raise TypeError(f"{field_name} must be a tuple of ExperienceItem values")
        if type(self.diagnostics) is not tuple or any(
            not isinstance(item, Mapping) for item in self.diagnostics
        ):
            raise TypeError("diagnostics must be a tuple of mappings")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_freeze(item) for item in self.diagnostics),
        )


def thaw_snapshot(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_snapshot(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_snapshot(item) for item in value]
    return value
