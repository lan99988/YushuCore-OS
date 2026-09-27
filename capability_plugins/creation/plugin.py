from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset(
    {
        "creation.capture_proposal",
        "creation.transition_proposal",
        "creation.feedback_proposal",
    }
)
_LIFECYCLE = ("idea", "draft", "production", "publish", "feedback", "archive")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class CreationPluginError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    directory = Path(__file__).resolve().parents[1] / "manifests"
    return next(item for item in load_manifests(directory) if item.plugin_id == "creation")


class CreationPlugin:
    def __init__(self) -> None:
        self.manifest = _load_manifest()

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        del context
        if capability not in _CAPABILITIES:
            raise CreationPluginError("unsupported_capability")
        if type(payload) is not dict:
            raise CreationPluginError("invalid_payload")
        if capability == "creation.capture_proposal":
            return self._capture(payload)
        if capability == "creation.transition_proposal":
            return self._transition(payload)
        return self._feedback(payload)

    @staticmethod
    def _capture(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"creation_id", "title", "knowledge_ref"}
        if set(payload) - allowed:
            raise CreationPluginError("invalid_fields")
        creation_id = _required_id(payload.get("creation_id"))
        title = _required_text(payload.get("title"))
        item = {"creation_id": creation_id, "title": title, "status": "idea"}
        reference = payload.get("knowledge_ref")
        if reference is not None:
            item["knowledge_ref"] = _required_id(reference)
        return _proposal("creation_capture", item=item)

    @staticmethod
    def _transition(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"creation_id", "from_status", "to_status"}:
            raise CreationPluginError("invalid_fields")
        creation_id = _required_id(payload.get("creation_id"))
        source = payload.get("from_status")
        target = payload.get("to_status")
        if source not in _LIFECYCLE or target not in _LIFECYCLE:
            raise CreationPluginError("invalid_status")
        if _LIFECYCLE.index(target) != _LIFECYCLE.index(source) + 1:
            raise CreationPluginError("invalid_transition")
        return _proposal(
            "creation_transition",
            creation_id=creation_id,
            transition={"from": source, "to": target},
        )

    @staticmethod
    def _feedback(payload: dict[str, Any]) -> dict[str, Any]:
        creation_id = _required_id(payload.get("creation_id"))
        summary = _required_text(payload.get("feedback_summary"))
        if set(payload) - {"creation_id", "feedback_summary"}:
            raise CreationPluginError("invalid_fields")
        return _proposal(
            "creation_feedback",
            creation_id=creation_id,
            feedback_summary=summary,
        )


def _proposal(proposal_type: str, **values: Any) -> dict[str, Any]:
    return {
        "proposal_type": proposal_type,
        **values,
        "status": "pending_human_review",
        "executed": False,
        "requires_human_review": True,
    }


def _required_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise CreationPluginError("invalid_identifier")
    return value


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise CreationPluginError("invalid_text")
    return value.strip()
