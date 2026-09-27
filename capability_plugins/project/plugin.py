from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests
from information_system.projects import ProjectRecord, ProjectResolver


_CAPABILITIES = frozenset(
    {
        "project.list",
        "project.context",
        "project.create_proposal",
        "project.milestone_proposal",
    }
)
_MILESTONE_FIELDS = frozenset({"title", "description", "due_at"})


class ProjectPluginError(ValueError):
    """Safe, stable errors exposed by Project capability calls."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "project":
            return manifest
    raise RuntimeError("project manifest is missing")


class ProjectPlugin:
    """Thin adapter over the configured ProjectResolver and legacy proposal builder."""

    def __init__(
        self,
        *,
        project_resolver: ProjectResolver | None = None,
        context_provider: Callable[[ProjectRecord], Mapping[str, Any]] | None = None,
    ) -> None:
        if project_resolver is not None and not isinstance(
            project_resolver, ProjectResolver
        ):
            raise TypeError("project_resolver must be a ProjectResolver")
        if context_provider is not None and not callable(context_provider):
            raise TypeError("context_provider must be callable")
        self.manifest = _load_manifest()
        self._resolver = project_resolver or ProjectResolver.from_config()
        self._context_provider = context_provider

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> Any:
        del context
        if capability not in _CAPABILITIES:
            raise ProjectPluginError(
                "unsupported_capability",
                "The requested Project capability is unsupported.",
            )
        if type(payload) is not dict:
            raise ProjectPluginError(
                "invalid_input", "Project payload must be a dictionary."
            )
        if capability == "project.list":
            return self._list(payload)
        if capability == "project.context":
            return self._context(payload)
        if capability == "project.create_proposal":
            return self._create_proposal(payload)
        return self._milestone_proposal(payload)

    def _list(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query", "")
        if not isinstance(query, str):
            raise ProjectPluginError("invalid_input", "Project query must be text.")
        records = self._resolver.projects
        if query.strip():
            matches = self._resolver.resolve(title=query, text=query)
            names = {match.label for match in matches}
            records = tuple(record for record in records if record.name in names)
        return {"projects": [_record_payload(record) for record in records]}

    def _context(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._resolve_record(payload.get("project_id"))
        if self._context_provider is None:
            return {
                "project": _record_payload(record),
                "context": None,
                "context_status": "registry_only",
            }
        try:
            result = self._context_provider(record)
            if not isinstance(result, Mapping):
                raise TypeError("invalid context result")
            copied = json.loads(
                json.dumps(dict(result), ensure_ascii=False, allow_nan=False)
            )
            return {"project": _record_payload(record), "context": copied}
        except Exception:
            raise ProjectPluginError(
                "project_context_failed", "Project context could not be read safely."
            ) from None

    @staticmethod
    def _create_proposal(payload: dict[str, Any]) -> dict[str, Any]:
        goal = payload.get("goal")
        statuses = payload.get("task_status", {})
        progress = payload.get("progress", 0.0)
        if not isinstance(goal, str) or not goal.strip():
            raise ProjectPluginError("invalid_input", "A Project goal is required.")
        if type(statuses) is not dict or any(
            not isinstance(task, str)
            or not task.strip()
            or not isinstance(status, str)
            or not status.strip()
            for task, status in statuses.items()
        ):
            raise ProjectPluginError("invalid_input", "Project task status is invalid.")
        if isinstance(progress, bool) or not isinstance(progress, (int, float)):
            raise ProjectPluginError("invalid_input", "Project progress is invalid.")
        try:
            from agents.project_execution import build_project_plan

            proposal = build_project_plan(
                goal.strip(), task_status=statuses, progress=float(progress)
            )
        except ValueError:
            raise ProjectPluginError("invalid_input", "Project plan fields are invalid.") from None
        except Exception:
            raise ProjectPluginError(
                "project_proposal_failed", "Project plan proposal failed safely."
            ) from None
        proposal = dict(proposal)
        proposal["approval"] = {
            "status": "pending_human_review",
            "reviewer": None,
            "reviewed_at": None,
        }
        proposal["status"] = "pending_human_review"
        proposal["executed"] = False
        proposal["requires_human_review"] = True
        return proposal

    def _milestone_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        proposal_id = payload.get("project_proposal_id")
        if proposal_id is not None:
            if not isinstance(proposal_id, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", proposal_id
            ):
                raise ProjectPluginError(
                    "invalid_input", "Project proposal identifier is invalid."
                )
            project_id = proposal_id
        else:
            project_id = self._resolve_record(payload.get("project_id")).name
        milestone = payload.get("milestone")
        if not isinstance(milestone, dict) or set(milestone) - _MILESTONE_FIELDS:
            raise ProjectPluginError("invalid_input", "Milestone fields are invalid.")
        title = milestone.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ProjectPluginError("invalid_input", "Milestone title is required.")
        copied_milestone: dict[str, str] = {"title": title.strip()}
        for field_name in ("description", "due_at"):
            value = milestone.get(field_name)
            if value is not None:
                if not isinstance(value, str):
                    raise ProjectPluginError(
                        "invalid_input", "Milestone fields are invalid."
                    )
                copied_milestone[field_name] = value.strip()
        return {
            "proposal_type": "project_milestone",
            "project_id": project_id,
            "milestone": copied_milestone,
            "approval": {
                "status": "pending_human_review",
                "reviewer": None,
                "reviewed_at": None,
            },
            "status": "pending_human_review",
            "executed": False,
            "requires_human_review": True,
        }

    def _resolve_record(self, project_id: Any) -> ProjectRecord:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ProjectPluginError("invalid_input", "A Project identifier is required.")
        token = project_id.strip().casefold()
        for record in self._resolver.projects:
            candidates = (record.name, *record.aliases)
            if any(token == candidate.casefold() for candidate in candidates):
                return record
        raise ProjectPluginError(
            "project_not_found", "The requested Project is not registered."
        )


def _record_payload(record: ProjectRecord) -> dict[str, Any]:
    return {"name": record.name, "aliases": list(record.aliases)}
