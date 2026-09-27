from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests
from personal_intelligence.engine import PersonalIntelligenceEngine
from personal_intelligence.execution import GoalExecutionPort
from personal_intelligence.models import Goal, SelfModelSnapshot


_CAPABILITIES = frozenset(
    {"goal.parse", "goal.current", "goal.gap", "goal.create_proposal"}
)
_GOAL_FIELDS = frozenset(
    {"goal_type", "title", "priority", "status", "related_domains"}
)


class GoalPluginError(ValueError):
    """Safe, stable errors exposed by Goal capability calls."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "goal":
            return manifest
    raise RuntimeError("goal manifest is missing")


class GoalPlugin:
    """Thin, read-only adapter over the existing Personal Intelligence Goal model."""

    def __init__(
        self,
        *,
        snapshot_provider: Callable[[], SelfModelSnapshot] | None = None,
        gap_analyzer: Callable[[Goal, tuple[Goal, ...]], Mapping[str, Any]] | None = None,
    ) -> None:
        if snapshot_provider is not None and not callable(snapshot_provider):
            raise TypeError("snapshot_provider must be callable")
        if gap_analyzer is not None and not callable(gap_analyzer):
            raise TypeError("gap_analyzer must be callable")
        self.manifest = _load_manifest()
        self._snapshot_provider = snapshot_provider
        self._gap_analyzer = gap_analyzer

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> Any:
        del context
        if capability not in _CAPABILITIES:
            raise GoalPluginError(
                "unsupported_capability", "The requested Goal capability is unsupported."
            )
        if type(payload) is not dict:
            raise GoalPluginError("invalid_input", "Goal payload must be a dictionary.")

        if capability == "goal.parse":
            return asdict(_parse_goal_payload(payload))
        if capability == "goal.current":
            return {"goals": [asdict(goal) for goal in self._current_goals()]}
        if capability == "goal.gap":
            return self._gap(payload)
        return self._create_proposal(payload)

    def _current_goals(self) -> tuple[Goal, ...]:
        if self._snapshot_provider is None:
            raise GoalPluginError(
                "goal_current_unavailable",
                "Current Goal data is not configured for this runtime.",
            )
        try:
            snapshot = self._snapshot_provider()
            if not isinstance(snapshot, SelfModelSnapshot):
                raise TypeError("invalid snapshot")
            analysis = PersonalIntelligenceEngine().plan_future(snapshot)
            goals = analysis["goals"]
            if not isinstance(goals, tuple) or any(
                not isinstance(goal, Goal) for goal in goals
            ):
                raise TypeError("invalid Goal model")
            return goals
        except Exception:
            raise GoalPluginError(
                "goal_current_failed", "Current Goal data could not be read safely."
            ) from None

    def _gap(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._gap_analyzer is None:
            raise GoalPluginError(
                "goal_gap_unavailable",
                "No Goal gap-analysis provider is configured for this runtime.",
            )
        target = _parse_goal_payload(payload)
        current = self._current_goals()
        try:
            result = self._gap_analyzer(target, current)
            if not isinstance(result, Mapping):
                raise TypeError("invalid gap result")
            serialized = json.dumps(
                dict(result), ensure_ascii=False, allow_nan=False
            )
            copied = json.loads(serialized)
            if not isinstance(copied, dict):
                raise TypeError("invalid gap result")
            return copied
        except Exception:
            raise GoalPluginError(
                "goal_gap_failed", "Goal gap analysis failed safely."
            ) from None

    @staticmethod
    def _create_proposal(payload: dict[str, Any]) -> dict[str, Any]:
        goal_id = payload.get("goal_id")
        title = payload.get("title")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise GoalPluginError("invalid_input", "A Goal identifier is required.")
        if not isinstance(title, str) or not title.strip():
            raise GoalPluginError("invalid_input", "A proposed task title is required.")
        try:
            return GoalExecutionPort().task_proposal(
                goal_id=goal_id.strip(),
                title=title.strip(),
                approved=False,
            )
        except Exception:
            raise GoalPluginError(
                "goal_proposal_failed", "The Goal proposal could not be created safely."
            ) from None


def _parse_goal_payload(payload: dict[str, Any]) -> Goal:
    values = payload.get("goal")
    if not isinstance(values, dict) or set(values) - _GOAL_FIELDS:
        raise GoalPluginError("invalid_input", "Goal fields are invalid.")
    title = values.get("title")
    if not isinstance(title, str) or not title.strip():
        raise GoalPluginError("invalid_input", "Goal fields are invalid.")
    normalized = {
        "goal_type": values.get("goal_type", "unspecified"),
        "title": title,
        "priority": values.get("priority", "unspecified"),
        "status": values.get("status", "proposed"),
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in normalized.values()
    ):
        raise GoalPluginError("invalid_input", "Goal fields are invalid.")
    domains = values.get("related_domains", ())
    if not isinstance(domains, (list, tuple)) or any(
        not isinstance(domain, str) or not domain.strip() for domain in domains
    ):
        raise GoalPluginError("invalid_input", "Goal fields are invalid.")
    return Goal(
        goal_type=normalized["goal_type"].strip(),
        title=normalized["title"].strip(),
        priority=normalized["priority"].strip(),
        status=normalized["status"].strip(),
        related_domains=tuple(domain.strip() for domain in domains),
    )
