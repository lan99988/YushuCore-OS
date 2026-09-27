from __future__ import annotations

from typing import Any

from .contracts import (
    ACTIVATION_MODES,
    ActivationState,
    Availability,
    PluginManifest,
    RiskLevel,
)


_REQUIRED_FIELDS = frozenset(
    {
        "plugin_id",
        "name",
        "version",
        "purpose",
        "domain",
        "provides",
        "reads",
        "writes",
        "dependencies",
        "permissions",
        "risk_level",
        "activation_mode",
    }
)
_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "availability": Availability.INSTALLED,
    "enabled": True,
    "activation_state": ActivationState.DORMANT,
    "input_contract": {},
    "output_contract": {},
    "error_policy": {},
    "audit_policy": {},
    "capability_priorities": {},
    "capability_priority_reasons": {},
    "capability_permissions": {},
    "capability_effects": {},
}
_ALLOWED_FIELDS = _REQUIRED_FIELDS | frozenset(_OPTIONAL_DEFAULTS)
_SEQUENCE_FIELDS = ("provides", "reads", "writes", "dependencies", "permissions")
_DICT_FIELDS = ("input_contract", "output_contract", "error_policy", "audit_policy")


def _enum_value(field_name: str, value: object, enum_type: type[Availability] | type[ActivationState] | type[RiskLevel]):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a {enum_type.__name__} value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _string_tuple(field_name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain only non-empty strings")
    return tuple(value)


def _string_dict(field_name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dictionary")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} keys must be strings")
    return dict(value)


def manifest_from_dict(data: dict[str, Any]) -> PluginManifest:
    """Convert one strict manifest mapping into a validated model."""
    if not isinstance(data, dict):
        raise ValueError("manifest must be a dict")
    if any(not isinstance(key, str) for key in data):
        raise ValueError("manifest keys must be strings")

    unknown_fields = set(data) - _ALLOWED_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(f"unknown manifest field(s): {unknown}")

    missing_fields = _REQUIRED_FIELDS - set(data)
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"missing required manifest field(s): {missing}")

    activation_mode = data["activation_mode"]
    if not isinstance(activation_mode, str) or activation_mode not in ACTIVATION_MODES:
        choices = ", ".join(sorted(ACTIVATION_MODES))
        raise ValueError(f"activation_mode must be one of: {choices}")

    values: dict[str, Any] = {field_name: data[field_name] for field_name in _REQUIRED_FIELDS}
    values["risk_level"] = _enum_value("risk_level", data["risk_level"], RiskLevel)

    values["availability"] = _enum_value(
        "availability",
        data.get("availability", _OPTIONAL_DEFAULTS["availability"]),
        Availability,
    )
    values["activation_state"] = _enum_value(
        "activation_state",
        data.get("activation_state", _OPTIONAL_DEFAULTS["activation_state"]),
        ActivationState,
    )
    values["enabled"] = data.get("enabled", _OPTIONAL_DEFAULTS["enabled"])

    for field_name in _SEQUENCE_FIELDS:
        values[field_name] = _string_tuple(field_name, data[field_name])
    for field_name in _DICT_FIELDS:
        values[field_name] = _string_dict(
            field_name,
            data.get(field_name, _OPTIONAL_DEFAULTS[field_name]),
        )
    values["capability_priorities"] = _string_dict(
        "capability_priorities",
        data.get("capability_priorities", _OPTIONAL_DEFAULTS["capability_priorities"]),
    )
    values["capability_priority_reasons"] = _string_dict(
        "capability_priority_reasons",
        data.get(
            "capability_priority_reasons",
            _OPTIONAL_DEFAULTS["capability_priority_reasons"],
        ),
    )
    raw_capability_permissions = _string_dict(
        "capability_permissions",
        data.get(
            "capability_permissions", _OPTIONAL_DEFAULTS["capability_permissions"]
        ),
    )
    values["capability_permissions"] = {
        capability: _string_tuple(
            f"capability_permissions[{capability}]", permissions
        )
        for capability, permissions in raw_capability_permissions.items()
    }
    values["capability_effects"] = _string_dict(
        "capability_effects",
        data.get("capability_effects", _OPTIONAL_DEFAULTS["capability_effects"]),
    )

    return PluginManifest(**values)
