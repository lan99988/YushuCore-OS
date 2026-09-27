from __future__ import annotations

from dataclasses import replace

import pytest

from capability_plugins.contracts import (
    ActivationState,
    Availability,
    PluginManifest,
    RiskLevel,
)
from capability_plugins.loader import load_manifests
from capability_plugins.lifecycle import PluginLifecycle
from capability_plugins.registry import PluginRegistry, PluginResolutionError


def _manifest(
    plugin_id: str,
    *,
    domain: str | None = None,
    provides: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
    activation_mode: str = "always",
    availability: Availability = Availability.INSTALLED,
    enabled: bool = True,
    activation_state: ActivationState = ActivationState.ACTIVE,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        name=f"{plugin_id.title()} Plugin",
        version="1.0.0",
        purpose=f"Test {plugin_id} capability",
        domain=domain or plugin_id,
        provides=provides,
        reads=(),
        writes=(),
        dependencies=dependencies,
        permissions=(),
        risk_level=RiskLevel.LOW,
        activation_mode=activation_mode,
        availability=availability,
        enabled=enabled,
        activation_state=activation_state,
    )


def test_registry_rejects_duplicate_plugin_id():
    registry = PluginRegistry()
    registry.register(_manifest("task"))

    with pytest.raises(ValueError, match="duplicate|already registered|already exists"):
        registry.register(_manifest("task", domain="other"))


def test_registry_rejects_ambiguous_capability_provider():
    registry = PluginRegistry()
    registry.register(_manifest("task", provides=("task.read",)))

    with pytest.raises(ValueError, match="priority|ambiguous|provider"):
        registry.register(_manifest("legacy_task", provides=("task.read",)))


def test_failed_registration_is_transactional():
    registry = PluginRegistry()
    registry.register(_manifest("task", provides=("shared.read",)))
    audit_before = registry.audit_events

    with pytest.raises(ValueError, match="priority|ambiguous|provider"):
        registry.register(
            _manifest(
                "candidate",
                provides=("candidate.unique", "shared.read"),
            )
        )

    with pytest.raises(KeyError, match="candidate"):
        registry.get("candidate")
    with pytest.raises(KeyError, match="candidate.unique"):
        registry.by_capability("candidate.unique")
    assert registry.audit_events == audit_before


def test_registry_selects_unique_highest_priority_provider():
    registry = PluginRegistry()
    capability = "task.read"
    registry.register(
        _manifest("task", provides=(capability,)),
        capability_priorities={capability: 10},
        priority_reasons={capability: "Primary task adapter"},
    )
    registry.register(
        _manifest("legacy_task", provides=(capability,)),
        capability_priorities={capability: 2},
        priority_reasons={capability: "Compatibility adapter"},
    )

    assert registry.by_capability(capability).plugin_id == "task"


def test_registry_skips_unready_high_priority_provider():
    registry = PluginRegistry()
    capability = "task.read"
    registry.register(
        _manifest("ready", provides=(capability,)),
        capability_priorities={capability: 2},
        priority_reasons={capability: "fallback_adapter"},
    )
    registry.register(
        _manifest(
            "dormant",
            provides=(capability,),
            activation_mode="on_demand",
            activation_state=ActivationState.DORMANT,
        ),
        capability_priorities={capability: 10},
        priority_reasons={capability: "preferred_when_active"},
    )

    assert registry.by_capability(capability).plugin_id == "ready"
    assert registry.list_enabled_capabilities() == [capability]


def test_registry_explains_when_no_capability_provider_is_ready():
    registry = PluginRegistry()
    registry.register(
        _manifest(
            "dormant",
            provides=("task.read",),
            activation_mode="on_demand",
            activation_state=ActivationState.DORMANT,
        )
    )

    with pytest.raises(PluginResolutionError, match="dormant") as error:
        registry.by_capability("task.read")

    assert error.value.status == "dormant"


@pytest.mark.parametrize(
    ("first_priorities", "first_reasons", "second_priorities", "second_reasons"),
    [
        ({}, {}, {"shared.read": 1}, {"shared.read": "Fallback"}),
        ({"shared.read": 2}, {"shared.read": "Preferred"}, {}, {}),
    ],
)
def test_registry_rejects_capability_conflict_without_priority_and_reason(
    first_priorities, first_reasons, second_priorities, second_reasons
):
    registry = PluginRegistry()
    capability = "shared.read"
    registry.register(
        _manifest("first", provides=(capability,)),
        capability_priorities=first_priorities,
        priority_reasons=first_reasons,
    )

    with pytest.raises(ValueError, match="priority|reason|provider|ambiguous"):
        registry.register(
            _manifest("second", provides=(capability,)),
            capability_priorities=second_priorities,
            priority_reasons=second_reasons,
        )


def test_registry_rejects_priority_without_reason():
    registry = PluginRegistry()

    with pytest.raises(ValueError, match="matching reason"):
        registry.register(
            _manifest("task", provides=("task.read",)),
            capability_priorities={"task.read": 2},
        )


def test_registry_rejects_tied_capability_priorities():
    registry = PluginRegistry()
    capability = "shared.read"
    registry.register(
        _manifest("first", provides=(capability,)),
        capability_priorities={capability: 5},
        priority_reasons={capability: "First adapter"},
    )

    with pytest.raises(ValueError, match="tie|equal|priority|ambiguous"):
        registry.register(
            _manifest("second", provides=(capability,)),
            capability_priorities={capability: 5},
            priority_reasons={capability: "Second adapter"},
        )


def test_dependency_validation_reports_missing_plugin():
    registry = PluginRegistry()
    registry.register(_manifest("task", dependencies=("calendar",)))

    with pytest.raises(ValueError, match="missing.*calendar|calendar.*missing"):
        registry.validate_dependencies()


@pytest.mark.parametrize(
    "dependency",
    [
        _manifest("dependency", enabled=False),
        _manifest("dependency", availability=Availability.UNAVAILABLE),
        _manifest("dependency", availability=Availability.ARCHIVED),
    ],
)
def test_dependency_validation_rejects_unavailable_dependency(dependency):
    registry = PluginRegistry()
    registry.register(dependency)
    registry.register(_manifest("consumer", dependencies=("dependency",)))

    with pytest.raises(ValueError, match="dependency.*not available"):
        registry.validate_dependencies()


def test_dependency_validation_rejects_self_reference():
    registry = PluginRegistry()
    registry.register(_manifest("task", dependencies=("task",)))

    with pytest.raises(ValueError, match="self.*depend|depend.*self"):
        registry.validate_dependencies()


def test_dependency_validation_rejects_cycle():
    registry = PluginRegistry()
    registry.register(_manifest("task", dependencies=("calendar",)))
    registry.register(_manifest("calendar", dependencies=("task",)))

    with pytest.raises(ValueError, match="cycle|circular"):
        registry.validate_dependencies()


def test_registry_queries_by_plugin_capability_and_domain():
    registry = PluginRegistry()
    task = _manifest("task", provides=("task.read",), domain="execution")
    registry.register(task)

    assert registry.get("task") == task
    assert registry.by_capability("task.read") == task
    assert registry.by_domain("execution") == [task]


def test_registry_builds_deterministic_capability_list_from_builtin_yaml():
    manifests = load_manifests("capability_plugins/manifests")

    registry = PluginRegistry.from_manifests(manifests)

    assert registry.list_enabled_capabilities() == [
        "calendar.check_conflict",
        "calendar.create_proposal",
        "calendar.find_free_slots",
        "calendar.list_events",
        "calendar.move_proposal",
        "information.capture",
        "information.get",
        "information.list_inbox",
        "information.propose_domain",
        "information.recognize",
        "knowledge.evidence_context",
        "knowledge.get",
        "knowledge.get_schema",
        "knowledge.health",
        "knowledge.read_context",
        "knowledge.search",
        "task.create_proposal",
        "task.list",
        "task.parse",
        "task.prioritize",
        "task.update_proposal",
    ]


def test_registry_build_is_independent_of_manifest_input_order():
    manifests = load_manifests("capability_plugins/manifests")

    forward = PluginRegistry.from_manifests(manifests)
    reverse = PluginRegistry.from_manifests(reversed(manifests))

    assert forward.list_enabled_capabilities() == reverse.list_enabled_capabilities()
    assert [event["plugin_id"] for event in forward.audit_events] == [
        event["plugin_id"] for event in reverse.audit_events
    ]


def test_registry_build_uses_priority_metadata_from_manifests():
    capability = "shared.read"
    primary = _manifest("primary", provides=(capability,))
    fallback = _manifest("fallback", provides=(capability,))
    primary = replace(
        primary,
        capability_priorities={capability: 10},
        capability_priority_reasons={capability: "primary_adapter"},
    )
    fallback = replace(
        fallback,
        capability_priorities={capability: 1},
        capability_priority_reasons={capability: "fallback_adapter"},
    )

    registry = PluginRegistry.from_manifests((fallback, primary))

    assert registry.by_capability(capability).plugin_id == "primary"


def test_registry_lists_only_enabled_installed_active_capabilities():
    registry = PluginRegistry()
    registry.register(_manifest("ready", provides=("ready.read",)))
    registry.register(
        _manifest("disabled", provides=("disabled.read",), enabled=False)
    )
    registry.register(
        _manifest(
            "unavailable",
            provides=("unavailable.read",),
            availability=Availability.UNAVAILABLE,
        )
    )
    registry.register(
        _manifest(
            "dormant",
            provides=("dormant.read",),
            activation_mode="on_demand",
            activation_state=ActivationState.DORMANT,
        )
    )
    registry.register(
        _manifest(
            "archived",
            provides=("archived.read",),
            availability=Availability.ARCHIVED,
        )
    )

    assert registry.list_enabled_capabilities() == ["ready.read"]


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        (_manifest("disabled", enabled=False), "disabled"),
        (
            _manifest(
                "dormant",
                activation_mode="on_demand",
                activation_state=ActivationState.DORMANT,
            ),
            "dormant",
        ),
        (
            _manifest("unavailable", availability=Availability.UNAVAILABLE),
            "unavailable",
        ),
        (_manifest("archived", availability=Availability.ARCHIVED), "archived"),
        (_manifest("missing", dependencies=("absent",)), "missing_dependency"),
        (_manifest("ready"), "ready"),
    ],
)
def test_registry_explains_distinct_plugin_states(manifest, expected):
    registry = PluginRegistry()
    registry.register(manifest)

    assert registry.explain(manifest.plugin_id)["status"] == expected


def test_lifecycle_activates_on_demand_plugin_and_records_metadata_only_audit():
    registry = PluginRegistry()
    manifest = _manifest(
        "information",
        provides=("information.capture",),
        activation_mode="on_demand",
        activation_state=ActivationState.DORMANT,
    )
    registry.register(manifest)
    lifecycle = PluginLifecycle(registry)

    lifecycle.transition(
        "information",
        activation_state=ActivationState.ACTIVE,
        actor="owner",
        reason="explicit_activation",
    )

    assert registry.explain("information")["status"] == "ready"
    assert registry.list_enabled_capabilities() == ["information.capture"]
    assert registry.audit_events
    assert all("payload" not in event for event in registry.audit_events)
    assert registry.audit_events[-1]["plugin_id"] == "information"
    assert registry.audit_events[-1]["action"] == "state_changed"
    assert registry.audit_events[-1]["actor"] == "owner"
    assert registry.audit_events[-1]["reason_code"] == "explicit_activation"


def test_registration_records_metadata_only_audit_event():
    registry = PluginRegistry()

    registry.register(_manifest("task", provides=("task.read",)))

    assert registry.audit_events == (
        {
            "plugin_id": "task",
            "action": "registered",
            "status": "ready",
            "actor": "registry",
            "reason_code": "manifest_registered",
        },
    )


def test_lifecycle_rejects_free_text_reason_without_audit():
    registry = PluginRegistry()
    registry.register(
        _manifest(
            "information",
            activation_mode="on_demand",
            activation_state=ActivationState.DORMANT,
        )
    )
    lifecycle = PluginLifecycle(registry)
    audit_before = registry.audit_events

    with pytest.raises(ValueError, match="reason code"):
        lifecycle.transition(
            "information",
            activation_state=ActivationState.ACTIVE,
            actor="owner",
            reason="contains sensitive free text",
        )

    assert registry.audit_events == audit_before


def test_invalid_lifecycle_transition_is_transactional():
    registry = PluginRegistry()
    manifest = _manifest("task", provides=("task.read",))
    registry.register(manifest)
    lifecycle = PluginLifecycle(registry)
    audit_before = registry.audit_events

    with pytest.raises(ValueError, match="always plugins cannot transition to dormant"):
        lifecycle.transition(
            "task",
            activation_state=ActivationState.DORMANT,
            actor="owner",
            reason="invalid_transition",
        )

    assert registry.get("task") == manifest
    assert registry.audit_events == audit_before
