from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Callable

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset(
    {
        "experience.record_proposal",
        "experience.transition_proposal",
        "experience.reflection_promotion_proposal",
    }
)
_LIFECYCLE = ("wishlist", "planned", "booked", "experienced", "reflection")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class ExperiencePluginError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    directory = Path(__file__).resolve().parents[1] / "manifests"
    return next(item for item in load_manifests(directory) if item.plugin_id == "experience")


class ExperiencePlugin:
    def __init__(
        self, *, status_reader: Callable[[str], str] | None = None
    ) -> None:
        if status_reader is not None and not callable(status_reader):
            raise TypeError("status_reader must be callable")
        self.manifest = _load_manifest()
        self._status_reader = status_reader

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        del context
        if capability not in _CAPABILITIES:
            raise ExperiencePluginError("unsupported_capability")
        if type(payload) is not dict:
            raise ExperiencePluginError("invalid_payload")
        if capability == "experience.record_proposal":
            return self._record(payload)
        if capability == "experience.transition_proposal":
            return self._transition(payload)
        return self._promote(payload)

    @staticmethod
    def _record(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"experience_id", "title", "scheduled_at"}:
            raise ExperiencePluginError("invalid_fields")
        event = {
            "experience_id": _identifier(payload.get("experience_id")),
            "title": _text(payload.get("title")),
            "status": "wishlist",
        }
        scheduled = payload.get("scheduled_at")
        if scheduled is not None:
            if not isinstance(scheduled, str):
                raise ExperiencePluginError("invalid_datetime")
            try:
                datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
            except ValueError:
                raise ExperiencePluginError("invalid_datetime") from None
            event["scheduled_at"] = scheduled
        return _proposal("experience_record", event=event)

    @staticmethod
    def _transition(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"experience_id", "from_status", "to_status"}:
            raise ExperiencePluginError("invalid_fields")
        source = payload.get("from_status")
        target = payload.get("to_status")
        if source not in _LIFECYCLE or target not in _LIFECYCLE:
            raise ExperiencePluginError("invalid_status")
        if _LIFECYCLE.index(target) != _LIFECYCLE.index(source) + 1:
            raise ExperiencePluginError("invalid_transition")
        return _proposal(
            "experience_transition",
            experience_id=_identifier(payload.get("experience_id")),
            transition={"from": source, "to": target},
        )

    def _promote(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("user_confirmed") is not True:
            raise ExperiencePluginError("explicit_confirmation_required")
        if set(payload) != {
            "experience_id",
            "reflection_ref",
            "target_type",
            "user_confirmed",
        }:
            raise ExperiencePluginError("invalid_fields")
        target = payload.get("target_type")
        if target not in {"experience", "principle"}:
            raise ExperiencePluginError("invalid_target_type")
        experience_id = _identifier(payload.get("experience_id"))
        if self._status_reader is None:
            raise ExperiencePluginError("experience_state_unavailable")
        try:
            current_status = self._status_reader(experience_id)
        except Exception:
            raise ExperiencePluginError("experience_state_unavailable") from None
        if current_status != "reflection":
            raise ExperiencePluginError("reflection_state_required")
        return _proposal(
            "reflection_promotion",
            experience_id=experience_id,
            reflection_ref=_identifier(payload.get("reflection_ref")),
            target_type=target,
        )


def _proposal(proposal_type: str, **values: Any) -> dict[str, Any]:
    return {
        "proposal_type": proposal_type,
        **values,
        "status": "pending_human_review",
        "executed": False,
        "requires_human_review": True,
    }


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ExperiencePluginError("invalid_identifier")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ExperiencePluginError("invalid_text")
    return value.strip()
