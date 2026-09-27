from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import importlib
from pathlib import Path
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset(
    {
        "task.parse",
        "task.list",
        "task.create_proposal",
        "task.update_proposal",
        "task.prioritize",
    }
)
_DELEGATE_CAPABILITIES = frozenset({"task.list", "task.prioritize"})


class TaskPluginError(ValueError):
    """Safe, stable errors returned by the Task capability adapter."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "task":
            return manifest
    raise RuntimeError("task manifest is missing")


class TaskPlugin:
    """Thin adapter over the existing Task parser and proposal builder.

    Task reads and prioritization are injected by the host. Proposal methods
    only return reviewable data; this adapter never persists or sends it.
    """

    def __init__(
        self,
        *,
        delegates: Mapping[str, Callable[..., Any]] | None = None,
    ) -> None:
        if delegates is None:
            delegates = {}
        if not isinstance(delegates, Mapping):
            raise TypeError("delegates must be a mapping")
        unknown = set(delegates) - _DELEGATE_CAPABILITIES
        if unknown:
            raise ValueError("unsupported delegate capability")
        if any(not callable(delegate) for delegate in delegates.values()):
            raise TypeError("every delegate must be callable")

        self.manifest = _load_manifest()
        self._delegates = dict(delegates)

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> Any:
        del context  # Runtime context is intentionally not exposed to legacy code.
        if capability not in _CAPABILITIES:
            raise TaskPluginError(
                "unsupported_capability", "The requested Task capability is unsupported."
            )
        if type(payload) is not dict:
            raise TaskPluginError("invalid_input", "Task payload must be a dictionary.")

        if capability == "task.parse":
            return self._parse(payload)
        if capability == "task.list":
            return self._delegate("task.list", payload.get("filters", {}), "task_list_failed")
        if capability == "task.prioritize":
            return self._delegate(
                "task.prioritize", payload.get("tasks"), "task_prioritize_failed"
            )
        if capability == "task.create_proposal":
            return self._create_proposal(payload)
        return self._update_proposal(payload)

    def _parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("text", payload.get("raw_text"))
        if not isinstance(text, str) or not text.strip():
            raise TaskPluginError("invalid_input", "Task text is required.")

        try:
            parser = importlib.import_module(
                "02_执行引擎（Engine）.输入解析引擎.parser"
            )
            builders = importlib.import_module(
                "02_执行引擎（Engine）.输入解析引擎.builders"
            )
            variables = parser.extract_variables(text)
            title = parser.extract_main_content(text)
            if not title:
                raise TaskPluginError("invalid_input", "Task title could not be parsed.")
            fields = builders.build_record("执行库", title, variables, raw_text=text)
        except TaskPluginError:
            raise
        except Exception:
            raise TaskPluginError(
                "task_parse_failed", "The existing Task parser could not parse this input."
            ) from None

        lightweight = "#临时" in text
        result: dict[str, Any] = {
            "ok": True,
            "type": "task_parse",
            "title": title,
            "variables": deepcopy(variables),
            "fields": deepcopy(fields),
            "lightweight": lightweight,
        }
        if lightweight:
            try:
                handler = importlib.import_module(
                    "02_执行引擎（Engine）.输入解析引擎.handlers.lightweight"
                )
                result["legacy_preview"] = handler.handle_lightweight_task(
                    text, dry_run=True
                )
            except Exception:
                raise TaskPluginError(
                    "lightweight_parse_failed",
                    "The existing lightweight Task handler could not parse this input.",
                ) from None
        return result

    def _delegate(self, capability: str, argument: Any, error_code: str) -> Any:
        delegate = self._delegates.get(capability)
        if delegate is None:
            unavailable_code = (
                "task_list_unavailable"
                if capability == "task.list"
                else "task_prioritizer_unavailable"
            )
            raise TaskPluginError(
                unavailable_code,
                "The requested Task service is not configured.",
            )
        if capability == "task.list" and type(argument) is not dict:
            raise TaskPluginError("invalid_input", "Task filters must be a dictionary.")
        if capability == "task.prioritize" and type(argument) is not list:
            raise TaskPluginError("invalid_input", "Tasks must be provided as a list.")
        try:
            return deepcopy(delegate(deepcopy(argument)))
        except Exception:
            raise TaskPluginError(error_code, "The Task service failed safely.") from None

    @staticmethod
    def _create_proposal(payload: dict[str, Any]) -> dict[str, Any]:
        from agents.project_execution import build_task_proposal

        title = payload.get("title")
        evidence = payload.get("evidence", [])
        project_id = payload.get("project_id", "")
        assignee = payload.get("assignee", "")
        due_at = payload.get("due_at", "")
        if not isinstance(title, str):
            raise TaskPluginError("invalid_input", "Task proposal title is required.")
        if type(evidence) is not list or any(not isinstance(item, str) for item in evidence):
            raise TaskPluginError("invalid_input", "Task proposal evidence must be strings.")
        if any(not isinstance(value, str) for value in (project_id, assignee, due_at)):
            raise TaskPluginError("invalid_input", "Task proposal metadata must be text.")
        try:
            return build_task_proposal(
                title,
                evidence=evidence,
                project_id=project_id,
                assignee=assignee,
                due_at=due_at,
            )
        except ValueError:
            raise TaskPluginError("invalid_input", "Task proposal input is invalid.") from None
        except Exception:
            raise TaskPluginError(
                "task_proposal_failed", "Task proposal generation failed safely."
            ) from None

    @staticmethod
    def _update_proposal(payload: dict[str, Any]) -> dict[str, Any]:
        task_guid = payload.get("task_guid")
        changes = payload.get("changes")
        if not isinstance(task_guid, str) or not task_guid.strip():
            raise TaskPluginError("invalid_input", "Task identifier is required.")
        if type(changes) is not dict or not changes:
            raise TaskPluginError("invalid_input", "Task changes must be a non-empty dictionary.")
        return {
            "proposal_type": "task_update",
            "task_guid": task_guid,
            "changes": deepcopy(changes),
            "approval": {
                "status": "pending_human_review",
                "reviewer": None,
                "reviewed_at": None,
            },
            "status": "pending_human_review",
            "execution_gateway": "feishu",
            "executed": False,
            "requires_human_review": True,
        }
