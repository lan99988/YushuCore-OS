from __future__ import annotations

import importlib
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Protocol, get_type_hints

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "capability_plugins"

VALID_MANIFEST = {
    "plugin_id": "task",
    "name": "Task Plugin",
    "version": "1.0.0",
    "purpose": "Manage task proposals",
    "domain": "task",
    "provides": ["task.list", "task.create_proposal"],
    "reads": ["feishu.task"],
    "writes": ["feishu.task"],
    "dependencies": [],
    "permissions": ["read_task", "propose_task_change"],
    "risk_level": "medium",
    "activation_mode": "always",
}


def _api():
    assert (PLUGIN_DIR / "__init__.py").is_file(), "capability_plugins package is missing"
    assert (PLUGIN_DIR / "contracts.py").is_file(), "capability plugin contracts are missing"
    assert (PLUGIN_DIR / "manifest.py").is_file(), "capability manifest converter is missing"
    return (
        importlib.import_module("capability_plugins.contracts"),
        importlib.import_module("capability_plugins.manifest"),
    )


def _manifest_data(**overrides):
    data = dict(VALID_MANIFEST)
    data.update(overrides)
    return data


def test_contracts_define_plugin_models_and_protocol():
    contracts, _ = _api()

    assert {member.value for member in contracts.Availability} == {
        "installed",
        "unavailable",
        "archived",
    }
    assert {member.value for member in contracts.ActivationState} == {"active", "dormant"}
    assert {member.value for member in contracts.RiskLevel} == {"low", "medium", "high"}
    assert contracts.PluginManifest.__dataclass_params__.frozen is True
    assert issubclass(contracts.CapabilityPlugin, Protocol)

    hints = get_type_hints(contracts.CapabilityPlugin)
    assert hints["manifest"] is contracts.PluginManifest
    invoke = inspect.signature(contracts.CapabilityPlugin.invoke)
    assert tuple(invoke.parameters) == ("self", "capability", "payload", "context")


def test_package_exports_wp1_public_api():
    package = importlib.import_module("capability_plugins")

    assert package.PluginRegistry.__name__ == "PluginRegistry"
    assert package.PluginLifecycle.__name__ == "PluginLifecycle"
    assert callable(package.load_manifests)


def test_manifest_from_dict_converts_lists_and_enum_values():
    contracts, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(VALID_MANIFEST)

    assert isinstance(manifest, contracts.PluginManifest)
    assert manifest.provides == ("task.list", "task.create_proposal")
    assert manifest.reads == ("feishu.task",)
    assert manifest.writes == ("feishu.task",)
    assert manifest.risk_level is contracts.RiskLevel.MEDIUM
    assert manifest.availability is contracts.Availability.INSTALLED
    assert manifest.activation_state is contracts.ActivationState.DORMANT
    assert manifest.enabled is True
    assert manifest.input_contract == {}
    assert manifest.output_contract == {}
    assert manifest.error_policy == {}
    assert manifest.audit_policy == {}
    assert manifest.capability_priorities == {}
    assert manifest.capability_priority_reasons == {}

    with pytest.raises(FrozenInstanceError):
        manifest.name = "Changed"


def test_manifest_from_dict_accepts_optional_enum_values():
    contracts, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(
        _manifest_data(
            availability="unavailable",
            enabled=False,
            activation_state="active",
        )
    )

    assert manifest.availability is contracts.Availability.UNAVAILABLE
    assert manifest.enabled is False
    assert manifest.activation_state is contracts.ActivationState.ACTIVE


def test_manifest_supports_capability_scoped_permissions_and_effects():
    _, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(
        _manifest_data(
            capability_permissions={
                "task.list": ["read_task"],
                "task.create_proposal": ["propose_task_change"],
            },
            capability_effects={
                "task.list": "read_only",
                "task.create_proposal": "proposal",
            },
        )
    )

    assert manifest.capability_permissions == {
        "task.list": ("read_task",),
        "task.create_proposal": ("propose_task_change",),
    }
    assert manifest.capability_effects == {
        "task.list": "read_only",
        "task.create_proposal": "proposal",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"capability_permissions": {"unknown.read": ["read_task"]}},
        {"capability_permissions": {"task.list": ["unknown_permission"]}},
        {"capability_permissions": {"task.list": "read_task"}},
        {"capability_effects": {"unknown.read": "read_only"}},
        {"capability_effects": {"task.list": "arbitrary"}},
    ],
)
def test_manifest_rejects_invalid_capability_scoped_policy(overrides):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="capability|permission|effect"):
        manifest_module.manifest_from_dict(_manifest_data(**overrides))


@pytest.mark.parametrize("field", ["plugin_id", "name", "version", "purpose", "domain"])
@pytest.mark.parametrize("value", ["", "   "])
def test_manifest_rejects_empty_required_text(field, value):
    _, manifest_module = _api()

    with pytest.raises(ValueError):
        manifest_module.manifest_from_dict(_manifest_data(**{field: value}))


@pytest.mark.parametrize(
    "domain",
    ["Body", "body.Area", ".body", "body.", "body..area", "body-area"],
)
def test_manifest_rejects_invalid_domain_identifier(domain):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="domain"):
        manifest_module.manifest_from_dict(_manifest_data(domain=domain))


def test_manifest_accepts_lowercase_dot_delimited_domain():
    _, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(_manifest_data(domain="health.body"))

    assert manifest.domain == "health.body"


@pytest.mark.parametrize("activation_mode", ["", None, "automatic", "always_on"])
def test_manifest_rejects_unsupported_activation_mode(activation_mode):
    _, manifest_module = _api()

    with pytest.raises(ValueError):
        manifest_module.manifest_from_dict(
            _manifest_data(activation_mode=activation_mode)
        )


@pytest.mark.parametrize("activation_mode", ["always", "on_demand"])
def test_manifest_accepts_supported_activation_modes(activation_mode):
    _, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(
        _manifest_data(activation_mode=activation_mode)
    )

    assert manifest.activation_mode == activation_mode


def test_manifest_rejects_duplicate_provides():
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="duplicate"):
        manifest_module.manifest_from_dict(
            _manifest_data(provides=["task.list", "task.list"])
        )


def test_manifest_rejects_unknown_risk_level():
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="risk_level"):
        manifest_module.manifest_from_dict(_manifest_data(risk_level="critical"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("availability", "removed"),
        ("activation_state", "paused"),
    ],
)
def test_manifest_rejects_unknown_enum_values(field, value):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match=field):
        manifest_module.manifest_from_dict(_manifest_data(**{field: value}))


@pytest.mark.parametrize("field", ["input_contract", "output_contract", "error_policy", "audit_policy"])
def test_manifest_rejects_non_dictionary_contract_fields(field):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match=field):
        manifest_module.manifest_from_dict(_manifest_data(**{field: []}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("provides", "task.list"),
        ("reads", [1]),
        ("writes", [None]),
        ("dependencies", [False]),
        ("permissions", [""]),
    ],
)
def test_manifest_rejects_invalid_string_sequences(field, value):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match=field):
        manifest_module.manifest_from_dict(_manifest_data(**{field: value}))


def test_manifest_rejects_non_boolean_enabled_value():
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="enabled"):
        manifest_module.manifest_from_dict(_manifest_data(enabled="false"))


def test_manifest_accepts_provider_priority_metadata():
    _, manifest_module = _api()

    manifest = manifest_module.manifest_from_dict(
        _manifest_data(
            capability_priorities={"task.list": 10},
            capability_priority_reasons={"task.list": "primary_adapter"},
        )
    )

    assert manifest.capability_priorities == {"task.list": 10}
    assert manifest.capability_priority_reasons == {"task.list": "primary_adapter"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"capability_priorities": {"unknown.read": 1}},
        {
            "capability_priorities": {"task.list": 1},
            "capability_priority_reasons": {},
        },
        {
            "capability_priorities": {"task.list": True},
            "capability_priority_reasons": {"task.list": "primary_adapter"},
        },
        {
            "capability_priorities": {"task.list": -1},
            "capability_priority_reasons": {"task.list": "primary_adapter"},
        },
        {
            "capability_priorities": {"task.list": 1},
            "capability_priority_reasons": {"task.list": ""},
        },
    ],
)
def test_manifest_rejects_invalid_provider_priority_metadata(overrides):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="priorit|reason|provided"):
        manifest_module.manifest_from_dict(_manifest_data(**overrides))


@pytest.mark.parametrize(
    "field",
    ["input_contract", "output_contract", "error_policy", "audit_policy"],
)
def test_manifest_rejects_non_string_contract_keys(field):
    _, manifest_module = _api()

    with pytest.raises(ValueError, match=field):
        manifest_module.manifest_from_dict(_manifest_data(**{field: {1: "value"}}))


def test_manifest_rejects_unknown_fields():
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="unknown"):
        manifest_module.manifest_from_dict(_manifest_data(unexpected="value"))


def test_manifest_rejects_non_dictionary_input():
    _, manifest_module = _api()

    with pytest.raises(ValueError, match="dict"):
        manifest_module.manifest_from_dict([("plugin_id", "task")])


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_manifest_rejects_missing_required_fields(field):
    _, manifest_module = _api()
    data = _manifest_data()
    del data[field]

    with pytest.raises(ValueError, match="missing"):
        manifest_module.manifest_from_dict(data)
