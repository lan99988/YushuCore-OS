from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Protocol


class Availability(str, Enum):
    INSTALLED = "installed"
    UNAVAILABLE = "unavailable"
    ARCHIVED = "archived"


class ActivationState(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


ACTIVATION_MODES = frozenset({"always", "on_demand"})
CAPABILITY_EFFECTS = frozenset(
    {"read_only", "proposal", "internal_write", "external_write"}
)
_DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


def _require_non_empty_text(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_string_tuple(field_name: str, value: object) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain only non-empty strings")


def _require_string_dict(field_name: str, value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dictionary")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} keys must be strings")


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    purpose: str
    domain: str
    provides: tuple[str, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    dependencies: tuple[str, ...]
    permissions: tuple[str, ...]
    risk_level: RiskLevel
    activation_mode: str
    availability: Availability = Availability.INSTALLED
    enabled: bool = True
    activation_state: ActivationState = ActivationState.DORMANT
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    error_policy: dict[str, Any] = field(default_factory=dict)
    audit_policy: dict[str, Any] = field(default_factory=dict)
    capability_priorities: dict[str, int] = field(default_factory=dict)
    capability_priority_reasons: dict[str, str] = field(default_factory=dict)
    capability_permissions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    capability_effects: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("plugin_id", "name", "version", "purpose", "domain"):
            _require_non_empty_text(field_name, getattr(self, field_name))

        if not _DOMAIN_PATTERN.fullmatch(self.domain):
            raise ValueError(
                "domain must be a lowercase dot-delimited identifier"
            )

        if self.activation_mode not in ACTIVATION_MODES:
            choices = ", ".join(sorted(ACTIVATION_MODES))
            raise ValueError(f"activation_mode must be one of: {choices}")

        for field_name in ("provides", "reads", "writes", "dependencies", "permissions"):
            _require_string_tuple(field_name, getattr(self, field_name))

        if len(self.provides) != len(set(self.provides)):
            raise ValueError("provides must not contain duplicate capabilities")

        for field_name, enum_type in (
            ("risk_level", RiskLevel),
            ("availability", Availability),
            ("activation_state", ActivationState),
        ):
            if not isinstance(getattr(self, field_name), enum_type):
                raise ValueError(f"{field_name} must be a {enum_type.__name__}")

        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")

        for field_name in (
            "input_contract",
            "output_contract",
            "error_policy",
            "audit_policy",
        ):
            _require_string_dict(field_name, getattr(self, field_name))

        if not isinstance(self.capability_priorities, dict):
            raise ValueError("capability_priorities must be a dictionary")
        if not isinstance(self.capability_priority_reasons, dict):
            raise ValueError("capability_priority_reasons must be a dictionary")
        if set(self.capability_priorities) != set(self.capability_priority_reasons):
            raise ValueError("every capability priority must have a matching reason")
        unknown_priorities = set(self.capability_priorities) - set(self.provides)
        if unknown_priorities:
            raise ValueError(
                "priority metadata references capabilities not provided by plugin: "
                + ", ".join(sorted(unknown_priorities))
            )
        for capability, priority in self.capability_priorities.items():
            if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
                raise ValueError(
                    f"priority for {capability} must be a non-negative integer"
                )
            reason = self.capability_priority_reasons[capability]
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"priority reason for {capability} is required")

        if not isinstance(self.capability_permissions, dict):
            raise ValueError("capability_permissions must be a dictionary")
        if not isinstance(self.capability_effects, dict):
            raise ValueError("capability_effects must be a dictionary")
        unknown_policy_capabilities = (
            set(self.capability_permissions) | set(self.capability_effects)
        ) - set(self.provides)
        if unknown_policy_capabilities:
            raise ValueError(
                "capability policy references capabilities not provided by plugin: "
                + ", ".join(sorted(unknown_policy_capabilities))
            )
        declared_permissions = set(self.permissions)
        for capability, permissions in self.capability_permissions.items():
            _require_string_tuple(
                f"capability_permissions[{capability}]", permissions
            )
            unknown_permissions = set(permissions) - declared_permissions
            if unknown_permissions:
                raise ValueError(
                    f"capability permission for {capability} is not declared by plugin: "
                    + ", ".join(sorted(unknown_permissions))
                )
        for capability, effect in self.capability_effects.items():
            if effect not in CAPABILITY_EFFECTS:
                raise ValueError(
                    f"invalid capability effect for {capability}: {effect!r}"
                )


class CapabilityPlugin(Protocol):
    manifest: PluginManifest

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> Any:
        raise NotImplementedError
