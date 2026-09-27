from __future__ import annotations

from dataclasses import replace
import re

from capability_plugins.contracts import ActivationState, Availability
from capability_plugins.registry import PluginRegistry


_REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class PluginLifecycle:
    """Applies explicit, metadata-only state transitions to a registry."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def transition(
        self,
        plugin_id: str,
        *,
        enabled: bool | None = None,
        availability: Availability | None = None,
        activation_state: ActivationState | None = None,
        actor: str,
        reason: str,
    ) -> None:
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor is required")
        if not isinstance(reason, str) or not _REASON_CODE_PATTERN.fullmatch(reason):
            raise ValueError(
                "reason code must be a lowercase identifier of at most 64 characters"
            )

        current = self._registry.get(plugin_id)
        updated = replace(
            current,
            enabled=current.enabled if enabled is None else enabled,
            availability=current.availability if availability is None else availability,
            activation_state=(
                current.activation_state
                if activation_state is None
                else activation_state
            ),
        )

        if (
            updated.activation_state is ActivationState.ACTIVE
            and (not updated.enabled or updated.availability is not Availability.INSTALLED)
        ):
            raise ValueError("only enabled, installed plugins can be activated")
        if (
            updated.activation_state is ActivationState.DORMANT
            and updated.activation_mode == "always"
            and updated.enabled
            and updated.availability is Availability.INSTALLED
        ):
            raise ValueError("always plugins cannot transition to dormant while enabled")

        if updated != current:
            self._registry._replace_manifest(
                updated,
                action="state_changed",
                actor=actor.strip(),
                reason_code=reason,
            )
