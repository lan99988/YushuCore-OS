from __future__ import annotations

from pathlib import Path

import yaml

from .contracts import PluginManifest
from .manifest import manifest_from_dict


def load_manifests(manifest_dir: str | Path) -> tuple[PluginManifest, ...]:
    """Load validated YAML declarations without importing plugin implementations."""
    directory = Path(manifest_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"manifest directory does not exist: {directory}")

    paths = sorted(directory.glob("*.yaml"), key=lambda item: item.name)
    if not paths:
        raise ValueError(f"no manifest YAML files found in: {directory}")

    manifests: list[PluginManifest] = []
    seen_ids: set[str] = set()

    for path in paths:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"empty manifest file: {path.name}")

        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError(f"manifest must be a mapping: {path.name}")

        manifest = manifest_from_dict(payload)
        if manifest.plugin_id in seen_ids:
            raise ValueError(f"duplicate plugin_id: {manifest.plugin_id}")
        if manifest.plugin_id in manifest.dependencies:
            raise ValueError(f"self-dependency for plugin_id: {manifest.plugin_id}")

        seen_ids.add(manifest.plugin_id)
        manifests.append(manifest)

    by_id = {manifest.plugin_id: manifest for manifest in manifests}
    for manifest in manifests:
        missing = sorted(set(manifest.dependencies) - by_id.keys())
        if missing:
            raise ValueError(
                f"missing dependency for {manifest.plugin_id}: {', '.join(missing)}"
            )

    _reject_dependency_cycles(by_id)
    return tuple(manifests)


def _reject_dependency_cycles(manifests: dict[str, PluginManifest]) -> None:
    states: dict[str, int] = {}
    stack: list[str] = []

    def visit(plugin_id: str) -> None:
        state = states.get(plugin_id, 0)
        if state == 2:
            return
        if state == 1:
            cycle_start = stack.index(plugin_id)
            cycle = stack[cycle_start:] + [plugin_id]
            raise ValueError(f"dependency cycle: {' -> '.join(cycle)}")

        states[plugin_id] = 1
        stack.append(plugin_id)
        dependencies = manifests[plugin_id].dependencies
        for dependency in sorted(dependencies):
            visit(dependency)
        stack.pop()
        states[plugin_id] = 2

    for plugin_id in sorted(manifests):
        visit(plugin_id)
