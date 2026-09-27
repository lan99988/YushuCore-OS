from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import yaml

from capability_plugins.contracts import PluginManifest
from capability_plugins.manifest import manifest_from_dict


CALENDAR_CAPABILITIES = (
    "calendar.list_events",
    "calendar.find_free_slots",
    "calendar.check_conflict",
    "calendar.create_proposal",
    "calendar.move_proposal",
)


class CalendarPluginError(RuntimeError):
    """Stable adapter error without legacy command output or event body text."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class CalendarDelegate(Protocol):
    """Injected read-only bridge to the legacy calendar API."""

    def check_date_freebusy(self, target_date: str | None = None) -> list[dict[str, Any]]:
        ...

    def find_next_available_slot(
        self, duration_minutes: int, after_iso: str
    ) -> dict[str, Any] | None:
        ...

    def check_slot_freebusy(
        self, slot_start_iso: str, slot_end_iso: str
    ) -> tuple[list[dict[str, Any]], bool]:
        ...


class _StrictLegacyCalendarDelegate:
    """Ask the legacy module to surface backend failures instead of sentinels."""

    def __init__(self, module: Any) -> None:
        self._module = module

    def check_date_freebusy(self, target_date: str | None = None) -> Any:
        return self._module.check_date_freebusy(target_date, strict=True)

    def find_next_available_slot(
        self, duration_minutes: int, after_iso: str
    ) -> Any:
        return self._module.find_next_available_slot(
            duration_minutes, after_iso, strict=True
        )

    def check_slot_freebusy(self, slot_start_iso: str, slot_end_iso: str) -> Any:
        return self._module.check_slot_freebusy(
            slot_start_iso, slot_end_iso, strict=True
        )


def _load_manifest() -> PluginManifest:
    manifest_path = Path(__file__).resolve().parents[1] / "manifests" / "calendar.yaml"
    manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict):
        raise ValueError("calendar manifest must be a mapping")
    return manifest_from_dict(manifest_data)


_MANIFEST = _load_manifest()


def _required_text(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided")
    return value


class CalendarPlugin:
    """Adapt read-only calendar calls; event changes remain human-reviewed proposals."""

    manifest = _MANIFEST

    def __init__(self, delegate: CalendarDelegate | None = None) -> None:
        self._delegate = delegate

    @classmethod
    def from_legacy_module(cls, module: Any | None = None) -> "CalendarPlugin":
        """Explicitly bridge the existing calendar_sync module when network is allowed."""
        legacy_module = module if module is not None else _load_legacy_calendar_module()
        return cls(_StrictLegacyCalendarDelegate(legacy_module))

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        if capability not in CALENDAR_CAPABILITIES:
            raise CalendarPluginError("unsupported_capability")
        if not isinstance(payload, dict):
            raise TypeError("calendar payload must be a dict")

        if capability in {
            "calendar.list_events",
            "calendar.find_free_slots",
            "calendar.check_conflict",
        }:
            network_mode = context.get("network_mode") if isinstance(context, dict) else None
            if network_mode not in {"ASSIST", "SYNC"}:
                raise CalendarPluginError("network_access_disabled")

        if capability == "calendar.list_events":
            return self.list_events(payload)
        if capability == "calendar.find_free_slots":
            return self.find_free_slots(payload)
        if capability == "calendar.check_conflict":
            return self.check_conflict(payload)
        if capability == "calendar.create_proposal":
            return self.create_proposal(payload)
        return self.move_proposal(payload)

    def list_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_date = _optional_text(payload, "target_date")
        value = self._call_delegate("check_date_freebusy", target_date)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise CalendarPluginError("calendar_sync_failed")
        return {
            "ok": True,
            "type": "calendar",
            "events": [dict(item) for item in value],
        }

    def find_free_slots(self, payload: dict[str, Any]) -> dict[str, Any]:
        duration = payload.get("duration_minutes")
        if type(duration) is not int or duration <= 0:
            raise ValueError("duration_minutes must be a positive integer")
        after_iso = _required_text(payload, "after_iso")
        value = self._call_delegate(
            "find_next_available_slot", duration, after_iso
        )
        if value is not None and not isinstance(value, dict):
            raise CalendarPluginError("calendar_sync_failed")
        return {
            "ok": True,
            "type": "calendar",
            "slots": [] if value is None else [dict(value)],
        }

    def check_conflict(self, payload: dict[str, Any]) -> dict[str, Any]:
        start_iso = _required_text(payload, "start_iso")
        end_iso = _required_text(payload, "end_iso")
        value = self._call_delegate(
            "check_slot_freebusy", start_iso, end_iso
        )
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not isinstance(value[0], list)
            or any(not isinstance(item, dict) for item in value[0])
            or type(value[1]) is not bool
        ):
            raise CalendarPluginError("calendar_sync_failed")
        conflicts, is_free = value
        return {
            "ok": True,
            "type": "calendar",
            "conflicts": [dict(item) for item in conflicts],
            "is_free": is_free,
        }

    def create_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        _required_text(payload, "summary")
        _required_text(payload, "start_iso")
        _required_text(payload, "end_iso")
        return self._proposal("create", payload)

    def move_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        _required_text(payload, "event_id")
        _required_text(payload, "new_start_iso")
        _required_text(payload, "new_end_iso")
        return self._proposal("move", payload)

    def _proposal(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        markers = ("fixed_meeting", "external_commitment", "affects_commitment")
        for marker in markers:
            if marker in payload and type(payload[marker]) is not bool:
                raise ValueError(f"{marker} must be a boolean")
        affects_commitment = any(payload.get(marker, False) for marker in markers)
        proposal = {
            "operation": operation,
            "status": "pending_human_review",
            "executed": False,
            "changes": dict(payload),
            "affects_commitment": affects_commitment,
        }
        return {
            "ok": True,
            "type": "calendar",
            "status": "pending_human_review",
            "executed": False,
            "affects_commitment": affects_commitment,
            "proposal": proposal,
        }

    def _call_delegate(self, method_name: str, *args: Any) -> Any:
        if self._delegate is None:
            raise CalendarPluginError("calendar_module_unavailable")
        try:
            method = getattr(self._delegate, method_name, None)
            if not callable(method):
                raise CalendarPluginError("calendar_module_unavailable")
            return method(*args)
        except CalendarPluginError:
            raise
        except (ImportError, FileNotFoundError):
            raise CalendarPluginError("calendar_module_unavailable") from None
        except Exception:
            raise CalendarPluginError("calendar_sync_failed") from None


def _load_legacy_calendar_module() -> Any:
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "02_执行引擎（Engine）"
        / "每日排程引擎"
        / "calendar_sync.py"
    )
    spec = importlib.util.spec_from_file_location("_yushu_legacy_calendar_sync", path)
    if spec is None or spec.loader is None:
        raise CalendarPluginError("calendar_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        raise CalendarPluginError("calendar_module_unavailable") from None
    return module
