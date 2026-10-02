"""Manifest-driven plugin and capability discovery."""

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .manifest import CapabilitySpec, PluginSpec, RouteSpec, load_manifest, validate_schema


@dataclass(frozen=True)
class CapabilityBinding:
    plugin: PluginSpec
    capability: CapabilitySpec
    ready: bool
    reasons: tuple[str, ...]


class PluginRegistry:
    def __init__(self, roots: list[str | Path], config: dict[str, Any]):
        self.config = config
        self.plugins: dict[str, PluginSpec] = {}
        self.errors: list[dict[str, str]] = []
        self._version_errors: dict[str, str] = {}
        self._providers: dict[str, list[CapabilityBinding]] = defaultdict(list)
        manifests: list[Path] = []
        for value in roots:
            root = Path(value).expanduser().absolute()
            if not root.exists() or root.is_symlink():
                continue
            manifests.extend(root.glob("*/plugin.yaml"))
            manifests.extend(root.glob("*/plugin.yml"))
            manifests.extend(root.glob("*/**/plugin.yaml"))
        versions: dict[str, list[PluginSpec]] = defaultdict(list)
        for path in sorted(set(manifests)):
            try:
                spec = load_manifest(path)
                versions[spec.plugin_id].append(spec)
            except (OSError, ValueError, TypeError) as exc:
                self.errors.append({"manifest": path.name, "error": str(exc)})
        requested_versions = self.config.get("plugins", {}).get("versions", {})
        for plugin_id, candidates in versions.items():
            by_version: dict[str, list[PluginSpec]] = defaultdict(list)
            for candidate in candidates:
                by_version[candidate.version].append(candidate)
            duplicate = [version for version, entries in by_version.items() if len(entries) > 1]
            if duplicate:
                self._version_errors[plugin_id] = "duplicate_plugin_version"
            selected = requested_versions.get(plugin_id)
            if selected:
                matches = by_version.get(selected, [])
                if matches:
                    chosen = matches[0]
                else:
                    chosen = sorted(candidates, key=lambda item: item.version)[-1]
                    self._version_errors[plugin_id] = "selected_version_missing"
            elif len(by_version) > 1:
                chosen = sorted(candidates, key=lambda item: item.version)[-1]
                self._version_errors[plugin_id] = "version_selection_required"
            else:
                chosen = candidates[0]
            self.plugins[plugin_id] = chosen
        self._check_dependency_cycles()
        for spec in self.plugins.values():
            for capability in spec.capabilities:
                reasons = self._readiness(spec, capability)
                self._providers[capability.name].append(CapabilityBinding(spec, capability, not reasons, tuple(reasons)))

    def _check_dependency_cycles(self) -> None:
        graph = {plugin_id: [dep for dep in spec.dependencies if dep in self.plugins] for plugin_id, spec in self.plugins.items()}
        visiting: list[str] = []
        visited: set[str] = set()
        cyclic: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visiting:
                cyclic.update(visiting[visiting.index(plugin_id):])
                return
            if plugin_id in visited:
                return
            visiting.append(plugin_id)
            for dep in graph[plugin_id]:
                visit(dep)
            visiting.remove(plugin_id)
            visited.add(plugin_id)

        for plugin_id in graph:
            visit(plugin_id)
        if cyclic:
            self.errors.append({"manifest": "dependency-graph", "error": "插件依赖存在循环"})
        self._cyclic_plugins = cyclic

    def _dependency_ready(self, name: str, visiting: frozenset[str] = frozenset()) -> bool:
        if name in self.plugins:
            spec = self.plugins[name]
            selected = self.config.get("plugins", {}).get("versions", {}).get(name)
            if (name in visiting or name in self._version_errors or not spec.enabled or name in set(self.config["user_disabled"])
                    or (selected and selected != spec.version)
                    or (self.config.get("plugins", {}).get("verify_release_hash", True) and not spec.package_hash_verified)):
                return False
            return all(self._dependency_ready(dep, visiting | {name}) for dep in spec.dependencies)
        available = set(self.config.get("runtime", {}).get("available_dependencies", []))
        if name in available:
            return True
        executable = name.split(">", 1)[0].strip().split(" ", 1)[0]
        return bool(executable and shutil.which(executable))

    def _app_binding_reasons(self, spec: PluginSpec, capability: CapabilitySpec) -> list[str]:
        configured = self.config.get("bindings", {}).get("apps", {}).get(spec.plugin_id)
        if not isinstance(configured, dict) or not isinstance(configured.get("active_pointer"), str):
            return ["app_binding_missing"]
        pointer = Path(configured["active_pointer"]).expanduser()
        if not pointer.is_absolute() or not pointer.is_file() or pointer.is_symlink():
            return ["app_binding_missing"]
        try:
            for path in (pointer, *pointer.parents):
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    return ["app_binding_invalid"]
            binding = json.loads(pointer.read_text(encoding="utf-8-sig"))
            app_name = spec.plugin_id.removeprefix("app-")
            if not isinstance(binding, dict) or binding.get("app") != app_name:
                return ["app_binding_invalid"]
            if binding.get("version") != spec.version:
                return ["app_version_mismatch"]
            for key, require_file in (("release", False), ("config_file", True), ("python_executable", True), ("ledger_path", False)):
                value = binding.get(key)
                if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
                    return ["app_binding_invalid"]
                path = Path(value).expanduser()
                if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)() for item in (path, *path.parents)):
                    return ["app_binding_invalid"]
                if (require_file and not path.is_file()) or (key == "release" and not path.is_dir()):
                    return ["app_binding_invalid"]
            if capability.effect in {"internal_write", "external_write"}:
                if not self.config.get("project_ref"):
                    return ["project_binding_required"]
                core_ledger = self.config.get("state", {}).get("ledger_path", "")
                if not core_ledger:
                    return ["shared_ledger_unbound"]
                core_path = Path(core_ledger).expanduser()
                if not core_path.is_absolute():
                    core_path = Path(self.config["_config_root"]) / core_path
                if core_path.absolute() != Path(binding["ledger_path"]).expanduser().absolute():
                    return ["shared_ledger_mismatch"]
                if not Path(binding["ledger_path"]).expanduser().is_file():
                    return ["shared_ledger_missing"]
        except (OSError, ValueError, TypeError):
            return ["app_binding_invalid"]
        return []

    def _readiness(self, spec: PluginSpec, capability: CapabilitySpec) -> list[str]:
        reasons: list[str] = []
        disabled = set(self.config.get("user_disabled", []))
        if spec.plugin_id in disabled or set(spec.skill_names) & disabled:
            reasons.append("user_disabled")
        if not spec.enabled:
            reasons.append("plugin_disabled")
        selected_version = self.config.get("plugins", {}).get("versions", {}).get(spec.plugin_id)
        if selected_version and selected_version != spec.version:
            reasons.append("version_not_selected")
        if spec.plugin_id in self._cyclic_plugins:
            reasons.append("dependency_cycle")
        if spec.plugin_id in self._version_errors:
            reasons.append(self._version_errors[spec.plugin_id])
        if spec.plugin_type == "app":
            reasons.extend(self._app_binding_reasons(spec, capability))
        if self.config.get("plugins", {}).get("verify_release_hash", True) and not spec.package_hash_verified:
            reasons.append("package_hash_unverified")
        if not capability.enabled:
            reasons.append("capability_disabled")
        if not any(tuple(sys.version_info[:2]) >= tuple(map(int, runtime.removeprefix("python>=").split(".")))
                   for runtime in spec.supported_runtimes):
            reasons.append("runtime_unavailable")
        plugin_config = self.config.get("plugins", {}).get("config", {}).get(spec.plugin_id, {})
        if validate_schema(spec.configuration, plugin_config, path="插件配置"):
            reasons.append("plugin_configuration_invalid")
        if not capability.implemented:
            reasons.append("not_implemented")
        if capability.effect in {"internal_write", "external_write"} and not capability.verified:
            reasons.append("not_verified")
        if capability.effect in {"internal_write", "external_write"} and not capability.authorized:
            reasons.append("not_authorized")
        if capability.effect in {"internal_write", "external_write"} and not capability.intents:
            reasons.append("write_intents_not_declared")
        dependencies = tuple(dict.fromkeys((*spec.dependencies, *capability.dependencies)))
        reasons.extend(f"dependency_missing:{item}" for item in dependencies if not self._dependency_ready(item))
        resource_bindings = self.config.get("bindings", {}).get("resources", {})
        reasons.extend(f"resource_scope_unbound:{scope}" for _, scope in capability.resource_scopes
                       if not resource_bindings.get(scope))
        if not spec.runner.get("command"):
            reasons.append("runner_missing")
        if capability.effect in {"internal_write", "external_write"}:
            grants = set(self.config.get("permissions", {}).get("grants", []))
            denials = set(self.config.get("permissions", {}).get("denials", []))
            requested = set(capability.permissions) | set(spec.permissions)
            if {capability.name, spec.plugin_id} & denials or requested & denials:
                reasons.append("permission_denied")
            elif not ({capability.name, spec.plugin_id} & grants) and not (requested and requested <= grants):
                reasons.append("permission_not_granted")
        return reasons

    def providers(self, capability: str) -> tuple[CapabilityBinding, ...]:
        return tuple(self._providers.get(capability, ()))

    def resolve(self, capability: str) -> CapabilityBinding | None:
        providers = [binding for binding in self.providers(capability) if binding.ready]
        selected = self.config.get("bindings", {}).get("providers", {}).get(capability)
        if selected:
            providers = [binding for binding in providers if binding.plugin.plugin_id == selected]
        return providers[0] if len(providers) == 1 else None

    def route(self, text: str) -> dict[str, Any]:
        matches: list[tuple[RouteSpec, PluginSpec, str]] = []
        for spec in self.plugins.values():
            for route in spec.routes:
                for prefix in (route.prefix, *route.aliases):
                    if text.startswith(prefix):
                        matches.append((route, spec, prefix))
        if not matches:
            return {"status": "handoff", "intent": "chat", "reason": "natural_language_is_host_owned",
                    "route_basis": "host_natural_language"}
        matches.sort(key=lambda pair: (-len(pair[2]), pair[2], pair[1].plugin_id))
        width = len(matches[0][2])
        winners = [(route, spec, prefix) for route, spec, prefix in matches if len(prefix) == width]
        if len({(route.capability, spec.plugin_id) for route, spec, _ in winners}) > 1:
            return {"status": "needs_clarification", "route_basis": "manifest_prefix_tie",
                    "candidates": [{"plugin": spec.plugin_id, "capability": route.capability, "prefix": prefix} for route, spec, prefix in winners]}
        route, spec, prefix = winners[0]
        content = text[len(prefix):].strip() if route.strip_prefix else text
        binding = self.resolve(route.capability)
        if spec.plugin_id in set(self.config.get("user_disabled", [])) or not spec.enabled:
            binding = None
        return {
            "status": "routed" if binding else "unavailable",
            "plugin": binding.plugin.plugin_id if binding else spec.plugin_id,
            "route_plugin": spec.plugin_id,
            "capability": route.capability, "intent": route.intent, "prefix": prefix,
            "content": content, "route_basis": "manifest_longest_prefix", "missing_fields": [],
            "required_fields": list(binding.capability.inputs.get("required", [])) if binding else [],
            "reasons": [] if binding else self.unavailable_reasons(route.capability),
        }

    def unavailable_reasons(self, capability: str) -> list[str]:
        providers = self.providers(capability)
        if not providers:
            return ["capability_unregistered"]
        selected = self.config.get("bindings", {}).get("providers", {}).get(capability)
        if selected:
            selected_providers = tuple(binding for binding in providers if binding.plugin.plugin_id == selected)
            if not selected_providers:
                return ["selected_provider_missing"]
            providers = selected_providers
        ready = [binding for binding in providers if binding.ready]
        if len(ready) > 1:
            return ["provider_selection_required"]
        if len(ready) == 1:
            return []
        reasons = sorted({reason for binding in providers for reason in binding.reasons})
        return reasons or ["no_ready_provider"]

    def catalog(self) -> dict[str, Any]:
        entries = []
        for spec in sorted(self.plugins.values(), key=lambda item: item.plugin_id):
            capabilities = []
            for cap in spec.capabilities:
                binding = next((b for b in self._providers[cap.name] if b.plugin.plugin_id == spec.plugin_id), None)
                candidates = self.providers(cap.name)
                selected = self.config.get("bindings", {}).get("providers", {}).get(cap.name)
                capabilities.append({
                    "name": cap.name, "effect": cap.effect, "implemented": cap.implemented,
                    "verified": cap.verified, "authorized": cap.authorized, "enabled": cap.enabled,
                    "available": bool(binding and binding.ready and (not selected or selected == spec.plugin_id)),
                    "provider_selected": not selected or selected == spec.plugin_id,
                    "ambiguous_provider": len([b for b in candidates if b.ready]) > 1 and not selected,
                    "unavailable_reasons": list(binding.reasons) if binding else [],
                })
            plugin_state = ("disabled_by_user" if spec.plugin_id in set(self.config.get("user_disabled", []))
                            or set(spec.skill_names) & set(self.config.get("user_disabled", []))
                            else "disabled_by_manifest" if not spec.enabled
                            else "ready" if any(binding.plugin.plugin_id == spec.plugin_id and binding.ready
                                                for caps in self._providers.values() for binding in caps)
                            else "blocked")
            entries.append({"id": spec.plugin_id, "name": spec.name, "version": spec.version,
                            "lifecycle_state": plugin_state, "supported_runtimes": list(spec.supported_runtimes),
                            "error_policy": spec.error_policy, "audit_policy": spec.audit_policy,
                            "type": spec.plugin_type, "description": spec.description, "capabilities": capabilities})
        return {"plugins": entries, "manifest_errors": self.errors}


def discover_roots(config: dict[str, Any]) -> list[Path]:
    root = Path(config["_config_root"])
    roots = [root / "plugins"]
    project_file = config.get("_project_file")
    project_root = Path(project_file).parent if project_file else None
    for entry in config.get("plugins", {}).get("plugin_paths", []):
        path = Path(entry).expanduser()
        if not path.is_absolute():
            if project_root is None:
                raise ValueError("相对 plugin_paths 需要显式 project_file")
            path = project_root / path
        roots.append(path.absolute())
    return roots
