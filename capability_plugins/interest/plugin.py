from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
import math
from pathlib import Path
import re
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset(
    {
        "interest.record_proposal",
        "interest.exploration_proposal",
        "interest.project_conversion_proposal",
        "interest.review",
    }
)
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class InterestPluginError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    directory = Path(__file__).resolve().parents[1] / "manifests"
    return next(item for item in load_manifests(directory) if item.plugin_id == "interest")


class InterestPlugin:
    def __init__(
        self,
        review_port: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.manifest = _load_manifest()
        self._review_port = review_port

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        del context
        if capability not in _CAPABILITIES:
            raise InterestPluginError("unsupported_capability")
        if type(payload) is not dict:
            raise InterestPluginError("invalid_payload")
        if capability == "interest.record_proposal":
            return self._record(payload)
        if capability == "interest.exploration_proposal":
            return self._explore(payload)
        if capability == "interest.review":
            return self._review(payload)
        return self._convert(payload)

    def _review(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"interest_id"}:
            raise InterestPluginError("invalid_fields")
        interest_id = _identifier(payload.get("interest_id"))
        if not callable(self._review_port):
            raise InterestPluginError("interest_review_unavailable")
        value = self._review_port(interest_id)
        if not isinstance(value, Mapping):
            raise InterestPluginError("invalid_review_data")
        items = value.get("items")
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise InterestPluginError("invalid_review_data")
        normalized = []
        for item in items:
            if not isinstance(item, Mapping):
                raise InterestPluginError("invalid_review_data")
            title = item.get("title")
            summary = item.get("summary")
            source = item.get("source")
            observed_at = item.get("observed_at")
            confidence = item.get("confidence")
            if not all(
                isinstance(field, str) and field.strip()
                for field in (title, summary, source, observed_at)
            ):
                raise InterestPluginError("invalid_review_data")
            try:
                date.fromisoformat(observed_at)
            except ValueError:
                raise InterestPluginError("invalid_review_data") from None
            if (
                type(confidence) not in {int, float}
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise InterestPluginError("invalid_review_data")
            normalized.append(
                {
                    "title": title.strip(),
                    "summary": summary.strip(),
                    "source": source.strip(),
                    "observed_at": observed_at,
                    "confidence": confidence,
                }
            )
        return {"items": normalized}

    @staticmethod
    def _record(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"interest_id", "title", "knowledge_ref"}:
            raise InterestPluginError("invalid_fields")
        topic = {
            "interest_id": _identifier(payload.get("interest_id")),
            "title": _text(payload.get("title")),
        }
        if "knowledge_ref" in payload:
            topic["knowledge_ref"] = _identifier(payload["knowledge_ref"])
        return _proposal("interest_topic", topic=topic)

    @staticmethod
    def _explore(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"interest_id", "summary", "observed_at"}:
            raise InterestPluginError("invalid_fields")
        observed_at = payload.get("observed_at")
        if not isinstance(observed_at, str):
            raise InterestPluginError("invalid_date")
        try:
            date.fromisoformat(observed_at)
        except ValueError:
            raise InterestPluginError("invalid_date") from None
        return _proposal(
            "interest_exploration",
            event={
                "interest_id": _identifier(payload.get("interest_id")),
                "summary": _text(payload.get("summary")),
                "observed_at": observed_at,
            },
        )

    @staticmethod
    def _convert(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("user_requested") is not True:
            raise InterestPluginError("explicit_request_required")
        if set(payload) != {"interest_id", "project_title", "user_requested"}:
            raise InterestPluginError("invalid_fields")
        return _proposal(
            "interest_project_conversion",
            interest_id=_identifier(payload.get("interest_id")),
            project_title=_text(payload.get("project_title")),
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
        raise InterestPluginError("invalid_identifier")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InterestPluginError("invalid_text")
    return value.strip()
