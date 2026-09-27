from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Iterable
from typing import Any

from capability_plugins.contracts import ActivationState, Availability, PluginManifest


class PluginResolutionError(LookupError):
    """A capability exists, but none of its providers is currently ready."""

    def __init__(self, capability: str, plugin_id: str, status: str) -> None:
        self.capability = capability
        self.plugin_id = plugin_id
        self.status = status
        super().__init__(
            f"capability {capability!r} is unavailable: "
            f"provider {plugin_id!r} is {status}"
        )


class PluginRegistry:
    """In-memory manifest registry with deterministic capability resolution."""

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        self._providers: dict[str, list[str]] = {}
        self._priorities: dict[tuple[str, str], int] = {}
        self._priority_reasons: dict[tuple[str, str], str] = {}
        self._audit_events: list[dict[str, str]] = []

    @classmethod
    def from_manifests(cls, manifests: Iterable[PluginManifest]) -> "PluginRegistry":
        """Build a validated registry in stable plugin-id order."""
        registry = cls()
        for manifest in sorted(manifests, key=lambda item: item.plugin_id):
            registry.register(manifest)
        registry.validate_dependencies()
        return registry

    @property
    def audit_events(self) -> tuple[dict[str, str], ...]:
        """Return a copy of metadata-only registration and lifecycle events."""
        return tuple(dict(event) for event in self._audit_events)

    def register(
        self,
        manifest: PluginManifest,
        *,
        capability_priorities: Mapping[str, int] | None = None,
        priority_reasons: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(manifest, PluginManifest):
            raise TypeError("manifest must be a PluginManifest")
        if manifest.plugin_id in self._manifests:
            raise ValueError(f"duplicate plugin_id: {manifest.plugin_id}")

        priorities = dict(
            manifest.capability_priorities
            if capability_priorities is None
            else capability_priorities
        )
        reasons = dict(
            manifest.capability_priority_reasons
            if priority_reasons is None
            else priority_reasons
        )
        self._validate_priority_metadata(manifest, priorities, reasons)

        # An always-on plugin starts active when registered. Availability and
        # enabled remain separate gates in the effective readiness check.
        if manifest.activation_mode == "always" and manifest.activation_state is not ActivationState.ACTIVE:
            from dataclasses import replace

            manifest = replace(manifest, activation_state=ActivationState.ACTIVE)

        for capability in manifest.provides:
            existing_ids = self._providers.get(capability, [])
            if not existing_ids:
                continue
            contenders = [*existing_ids, manifest.plugin_id]
            for plugin_id in contenders:
                if (plugin_id, capability) in self._priorities:
                    continue
                if plugin_id == manifest.plugin_id and capability in priorities:
                    continue
                raise ValueError(
                    f"ambiguous capability provider for {capability}: "
                    "every provider needs an explicit priority and reason"
                )

            candidate_priority = priorities.get(capability)
            candidate_reason = reasons.get(capability)
            if candidate_priority is not None and candidate_reason is not None:
                contender_priorities = [
                    self._priorities[(plugin_id, capability)] for plugin_id in existing_ids
                ] + [candidate_priority]
                high_score = max(contender_priorities)
                if contender_priorities.count(high_score) > 1:
                    raise ValueError(
                        f"ambiguous capability provider for {capability}: "
                        "highest priority is tied"
                    )

        self._manifests[manifest.plugin_id] = manifest
        for capability in manifest.provides:
            self._providers.setdefault(capability, []).append(manifest.plugin_id)
        for capability, priority in priorities.items():
            self._priorities[(manifest.plugin_id, capability)] = priority
            self._priority_reasons[(manifest.plugin_id, capability)] = reasons[capability]

        self._record_event(
            manifest.plugin_id,
            "registered",
            actor="registry",
            reason_code="manifest_registered",
        )

    @staticmethod
    def _validate_priority_metadata(
        manifest: PluginManifest,
        priorities: Mapping[str, int],
        reasons: Mapping[str, str],
    ) -> None:
        if set(priorities) != set(reasons):
            raise ValueError("every capability priority must have a matching reason")
        unknown = (set(priorities) | set(reasons)) - set(manifest.provides)
        if unknown:
            raise ValueError(
                "priority metadata references capabilities not provided by plugin: "
                + ", ".join(sorted(unknown))
            )
        for capability, priority in priorities.items():
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise ValueError(f"priority for {capability} must be an integer")
            if priority < 0:
                raise ValueError(f"priority for {capability} must be non-negative")
            if not isinstance(reasons[capability], str) or not reasons[capability].strip():
                raise ValueError(f"priority reason for {capability} is required")

    def validate_dependencies(self) -> None:
        """Validate the complete registered dependency graph."""
        for plugin_id in sorted(self._manifests):
            for dependency in self._manifests[plugin_id].dependencies:
                if dependency == plugin_id:
                    raise ValueError(f"plugin {plugin_id} has a self dependency")
                if dependency not in self._manifests:
                    raise ValueError(
                        f"missing dependency {dependency!r} required by plugin {plugin_id}"
                    )
                dependency_manifest = self._manifests[dependency]
                if (
                    dependency_manifest.availability is not Availability.INSTALLED
                    or not dependency_manifest.enabled
                ):
                    raise ValueError(
                        f"dependency {dependency!r} required by plugin {plugin_id} "
                        "is not available"
                    )

        visiting: list[str] = []
        visited: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visited:
                return
            if plugin_id in visiting:
                cycle = visiting[visiting.index(plugin_id) :] + [plugin_id]
                raise ValueError("dependency cycle: " + " -> ".join(cycle))
            visiting.append(plugin_id)
            for dependency in sorted(self._manifests[plugin_id].dependencies):
                visit(dependency)
            visiting.pop()
            visited.add(plugin_id)

        for plugin_id in sorted(self._manifests):
            visit(plugin_id)

    def get(self, plugin_id: str) -> PluginManifest:
        try:
            return self._manifests[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin_id: {plugin_id}") from exc

    def by_capability(self, capability: str) -> PluginManifest:
        provider_ids = self._providers.get(capability)
        if not provider_ids:
            raise KeyError(f"unknown capability: {capability}")

        ready_provider_ids = [
            plugin_id
            for plugin_id in provider_ids
            if self._explain(plugin_id, visiting=())["status"] == "ready"
        ]
        if not ready_provider_ids:
            nominal_id = self._select_provider(capability, provider_ids)
            status = self._explain(nominal_id, visiting=())["status"]
            raise PluginResolutionError(capability, nominal_id, status)
        winner_id = self._select_provider(capability, ready_provider_ids)
        return self._manifests[winner_id]

    def _select_provider(self, capability: str, provider_ids: list[str]) -> str:
        return max(
            provider_ids,
            key=lambda plugin_id: (
                self._priorities.get((plugin_id, capability), 0),
                plugin_id,
            ),
        )

    def by_domain(self, domain: str) -> list[PluginManifest]:
        return sorted(
            (
                manifest
                for manifest in self._manifests.values()
                if manifest.domain == domain
            ),
            key=lambda manifest: manifest.plugin_id,
        )

    def list_enabled_capabilities(self) -> list[str]:
        capabilities = []
        for capability in sorted(self._providers):
            try:
                self.by_capability(capability)
            except PluginResolutionError:
                continue
            capabilities.append(capability)
        return capabilities

    def explain(self, plugin_id: str) -> dict[str, Any]:
        self.get(plugin_id)
        return self._explain(plugin_id, visiting=())

    def _explain(self, plugin_id: str, *, visiting: tuple[str, ...]) -> dict[str, Any]:
        manifest = self._manifests[plugin_id]
        status = "ready"
        reason = "plugin is ready"
        missing_dependencies: list[str] = []
        unavailable_dependencies: list[str] = []

        if manifest.availability is Availability.ARCHIVED:
            status, reason = "archived", "plugin is archived"
        elif manifest.availability is Availability.UNAVAILABLE:
            status, reason = "unavailable", "plugin implementation is unavailable"
        elif not manifest.enabled:
            status, reason = "disabled", "plugin is disabled"
        elif manifest.activation_state is ActivationState.DORMANT:
            status, reason = "dormant", "plugin is dormant"
        else:
            for dependency in manifest.dependencies:
                if dependency == plugin_id or dependency not in self._manifests:
                    missing_dependencies.append(dependency)
                    continue
                if dependency in visiting:
                    missing_dependencies.append(dependency)
                    continue
                dependency_status = self._explain(
                    dependency, visiting=(*visiting, plugin_id)
                )["status"]
                if dependency_status != "ready":
                    unavailable_dependencies.append(dependency)

            if missing_dependencies:
                status, reason = "missing_dependency", "one or more dependencies are missing"
                missing_dependencies.sort()
            elif unavailable_dependencies:
                status, reason = (
                    "dependency_unavailable",
                    "one or more dependencies are unavailable",
                )
                unavailable_dependencies.sort()

        return {
            "plugin_id": plugin_id,
            "status": status,
            "reason": reason,
            "missing_dependencies": tuple(
                [*missing_dependencies, *unavailable_dependencies]
            ),
        }

    def _replace_manifest(
        self,
        manifest: PluginManifest,
        *,
        action: str,
        actor: str,
        reason_code: str,
    ) -> None:
        if manifest.plugin_id not in self._manifests:
            raise KeyError(f"unknown plugin_id: {manifest.plugin_id}")
        self._manifests[manifest.plugin_id] = manifest
        self._record_event(
            manifest.plugin_id,
            action,
            actor=actor,
            reason_code=reason_code,
        )

    def _record_event(
        self,
        plugin_id: str,
        action: str,
        *,
        actor: str,
        reason_code: str,
    ) -> None:
        self._audit_events.append(
            {
                "plugin_id": plugin_id,
                "action": action,
                "status": self.explain(plugin_id)["status"],
                "actor": actor,
                "reason_code": reason_code,
            }
        )
