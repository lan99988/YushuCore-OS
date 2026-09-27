from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset(
    {
        "learning.current_state",
        "learning.progress",
        "learning.context",
    }
)


class LearningPluginError(ValueError):
    """Safe, stable error raised by the read-only Learning adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "learning":
            return manifest
    raise RuntimeError("learning manifest is missing")


class LearningPlugin:
    """Thin adapter over injected, read-only Learning state providers.

    The legacy Learning code exposes planning but no authoritative current-state
    or progress store. Those read sources therefore remain host-injected rather
    than being inferred or reimplemented here.
    """

    def __init__(
        self,
        *,
        delegates: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    ) -> None:
        if delegates is None:
            delegates = {}
        if not isinstance(delegates, Mapping):
            raise TypeError("delegates must be a mapping")
        unknown = set(delegates) - _CAPABILITIES
        if unknown:
            raise ValueError("unsupported delegate capability")
        if any(not callable(delegate) for delegate in delegates.values()):
            raise TypeError("every delegate must be callable")

        self.manifest = _load_manifest()
        self._delegates = dict(delegates)

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> Any:
        del context
        if capability not in _CAPABILITIES:
            raise LearningPluginError("unsupported_capability")
        if type(payload) is not dict:
            raise LearningPluginError("invalid_payload")
        delegate = self._delegates.get(capability)
        if delegate is None:
            raise LearningPluginError("learning_source_unavailable")
        try:
            return deepcopy(delegate(deepcopy(payload)))
        except Exception:
            raise LearningPluginError("learning_source_failed") from None
