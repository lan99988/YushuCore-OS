from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from agents.body_advisor import assess_body_snapshot
from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


class BodyPluginError(ValueError):
    """Safe, stable error raised by the read-only Body adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


SnapshotReader = Callable[[], Mapping[str, Any]]


def _body_tools_directory() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "08_工具脚本（Tools）"
        / "身体管理"
    )


def _load_policy(name: str) -> Any:
    """Import a known pure policy from the existing Body tools directory."""
    import importlib.util

    path = _body_tools_directory() / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_capability_body_{name}", path)
    if spec is None or spec.loader is None:
        raise BodyPluginError("body_policy_unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        raise BodyPluginError("body_policy_unavailable") from None
    return module


def _manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "body":
            return manifest
    raise RuntimeError("body plugin manifest is missing")


class BodyPlugin:
    """Expose existing Garmin/Body projections without owning data access."""

    def __init__(
        self,
        *,
        snapshot_reader: SnapshotReader | None = None,
    ) -> None:
        if snapshot_reader is not None and not callable(snapshot_reader):
            raise TypeError("snapshot_reader must be callable")
        self.manifest = _manifest()
        self._snapshot_reader = snapshot_reader

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> Any:
        del context  # The adapter does not need or persist caller context.
        if capability not in self.manifest.provides:
            raise BodyPluginError("unsupported_capability")
        if not isinstance(payload, dict):
            raise BodyPluginError("invalid_payload")

        snapshot = self._read_snapshot(payload)
        energy = snapshot.get("today_energy_context")
        training = snapshot.get("today_training_context")

        if capability == "body.current_energy":
            if not isinstance(energy, dict):
                raise BodyPluginError("energy_context_unavailable")
            return deepcopy(dict(energy))

        if capability == "body.training_context":
            if isinstance(training, dict):
                return deepcopy(dict(training))
            logs = snapshot.get("training_logs")
            if not isinstance(logs, list):
                raise BodyPluginError("training_context_unavailable")
            date_range = snapshot.get("date_range")
            today = date_range.get("end") if isinstance(date_range, dict) else None
            try:
                policy = _load_policy("training_policy")
                return policy.derive_training_policy(
                    logs,
                    today=today,
                    energy_context=energy if isinstance(energy, dict) else None,
                )
            except BodyPluginError:
                raise
            except Exception:
                raise BodyPluginError("training_context_unavailable") from None

        if capability == "body.recovery_context":
            recovery = snapshot.get("today_recovery_context")
            if isinstance(recovery, dict):
                return deepcopy(dict(recovery))
            try:
                policy = _load_policy("recovery_policy")
                return policy.derive_recovery_policy(
                    energy if isinstance(energy, dict) else None,
                    training if isinstance(training, dict) else None,
                )
            except BodyPluginError:
                raise
            except Exception:
                raise BodyPluginError("recovery_context_unavailable") from None

        # Preserve the legacy advisor's input and output contract verbatim.
        try:
            return assess_body_snapshot(dict(snapshot))
        except Exception:
            raise BodyPluginError("adjustment_unavailable") from None

    def _read_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._snapshot_reader is None:
            snapshot = payload.get("snapshot")
            if snapshot is None:
                raise BodyPluginError("snapshot_required")
        else:
            try:
                snapshot = self._snapshot_reader()
            except Exception:
                raise BodyPluginError("snapshot_unavailable") from None

        if not isinstance(snapshot, Mapping):
            raise BodyPluginError("invalid_snapshot")
        return dict(snapshot)
