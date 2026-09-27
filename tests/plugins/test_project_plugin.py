from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

from capability_plugins import ActivationState, Availability, load_manifests
from information_system.projects import ProjectRecord, ProjectResolver


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
EXPECTED_CAPABILITIES = (
    "project.list",
    "project.context",
    "project.create_proposal",
    "project.milestone_proposal",
)


def _api():
    try:
        spec = importlib.util.find_spec("capability_plugins.project.plugin")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "capability_plugins.project.plugin is required"
    module = importlib.import_module("capability_plugins.project.plugin")
    return module.ProjectPlugin, module.ProjectPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "project"
    )


def _resolver():
    return ProjectResolver(
        projects=(
            ProjectRecord("考研 408", ("408",)),
            ProjectRecord("Body OS", ("BodyOS",)),
        )
    )


def test_project_manifest_and_adapter_have_complete_on_demand_policy_metadata():
    ProjectPlugin, _ = _api()
    manifest = _manifest()

    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.capability_permissions.keys() == set(EXPECTED_CAPABILITIES)
    assert manifest.capability_effects.keys() == set(EXPECTED_CAPABILITIES)
    assert {"read_project", "propose_change"} <= set(manifest.permissions)
    assert manifest.capability_permissions["project.create_proposal"] == ("propose_change",)
    assert manifest.capability_permissions["project.milestone_proposal"] == ("propose_change",)
    assert manifest.capability_effects["project.create_proposal"] == "proposal"
    assert manifest.capability_effects["project.milestone_proposal"] == "proposal"
    assert manifest.availability is Availability.INSTALLED
    assert manifest.activation_mode == "on_demand"
    assert manifest.enabled is True
    assert manifest.activation_state is ActivationState.DORMANT
    assert ProjectPlugin().manifest == manifest


def test_project_list_uses_existing_config_resolver_records():
    ProjectPlugin, _ = _api()
    plugin = ProjectPlugin(project_resolver=_resolver())

    result = plugin.invoke("project.list", {}, {})

    assert result == {
        "projects": [
            {"name": "考研 408", "aliases": ["408"]},
            {"name": "Body OS", "aliases": ["BodyOS"]},
        ]
    }


def test_project_context_resolves_config_identity_and_uses_injected_read_only_context():
    ProjectPlugin, _ = _api()
    seen = []

    def read_context(project):
        seen.append(project.name)
        return {"status": "active", "milestones": ["第一轮"]}

    plugin = ProjectPlugin(
        project_resolver=_resolver(),
        context_provider=read_context,
    )
    result = plugin.invoke("project.context", {"project_id": "408"}, {})

    assert result == {
        "project": {"name": "考研 408", "aliases": ["408"]},
        "context": {"status": "active", "milestones": ["第一轮"]},
    }
    assert seen == ["考研 408"]


def test_project_context_without_runtime_provider_returns_registry_identity_only():
    ProjectPlugin, _ = _api()
    result = ProjectPlugin(project_resolver=_resolver()).invoke(
        "project.context", {"project_id": "Body OS"}, {}
    )

    assert result == {
        "project": {"name": "Body OS", "aliases": ["BodyOS"]},
        "context": None,
        "context_status": "registry_only",
    }


def test_project_create_proposal_reuses_legacy_project_plan_builder():
    ProjectPlugin, _ = _api()
    builder = importlib.import_module("agents.project_execution").build_project_plan
    payload = {
        "goal": "发布项目方案",
        "task_status": {"设计": "done", "评审": "blocked"},
        "progress": 0.5,
    }

    result = ProjectPlugin(project_resolver=_resolver()).invoke(
        "project.create_proposal", payload, {}
    )
    expected = builder(
        payload["goal"],
        task_status=payload["task_status"],
        progress=payload["progress"],
    )

    assert result["proposal_type"] == expected["proposal_type"]
    assert result["project_plan"] == expected["project_plan"]
    assert result["risk_analysis"] == expected["risk_analysis"]
    assert result["task_suggestions"] == expected["task_suggestions"]
    assert result["approval"]["status"] == "pending_human_review"
    assert result["status"] == "pending_human_review"
    assert result["executed"] is False
    assert result["requires_human_review"] is True


def test_project_milestone_proposal_is_data_only_and_requires_review():
    ProjectPlugin, _ = _api()
    milestone = {
        "title": "完成第一轮复习",
        "description": "完成教材和真题第一轮",
        "due_at": "2026-12-01",
    }

    result = ProjectPlugin(project_resolver=_resolver()).invoke(
        "project.milestone_proposal",
        {"project_id": "考研 408", "milestone": milestone},
        {},
    )

    assert result["proposal_type"] == "project_milestone"
    assert result["project_id"] == "考研 408"
    assert result["milestone"] == milestone
    assert result["status"] == "pending_human_review"
    assert result["approval"]["status"] == "pending_human_review"
    assert result["executed"] is False
    assert result["requires_human_review"] is True


def test_milestone_can_target_a_controlled_new_project_proposal():
    ProjectPlugin, _ = _api()

    result = ProjectPlugin(project_resolver=_resolver()).invoke(
        "project.milestone_proposal",
        {
            "project_proposal_id": "project-english",
            "milestone": {"title": "建立听力习惯"},
        },
        {},
    )

    assert result["project_id"] == "project-english"
    assert result["status"] == "pending_human_review"


def test_project_errors_are_stable_and_provider_details_are_sanitized():
    ProjectPlugin, ProjectPluginError = _api()

    def failing_context(_project):
        raise RuntimeError("private project state")

    plugin = ProjectPlugin(
        project_resolver=_resolver(),
        context_provider=failing_context,
    )
    with pytest.raises(ProjectPluginError) as context_error:
        plugin.invoke("project.context", {"project_id": "408"}, {})
    assert context_error.value.error_code == "project_context_failed"
    assert "private project state" not in str(context_error.value)
    assert context_error.value.__cause__ is None

    with pytest.raises(ProjectPluginError) as missing_error:
        plugin.invoke("project.context", {"project_id": "unknown"}, {})
    assert missing_error.value.error_code == "project_not_found"

    with pytest.raises(ProjectPluginError) as invalid_error:
        plugin.invoke("project.milestone_proposal", {"milestone": {}}, {})
    assert invalid_error.value.error_code == "invalid_input"

    with pytest.raises(ProjectPluginError) as capability_error:
        plugin.invoke("project.delete", {}, {})
    assert capability_error.value.error_code == "unsupported_capability"


def test_project_plugin_has_no_direct_network_or_external_write_imports():
    ProjectPlugin, _ = _api()
    module = importlib.import_module("capability_plugins.project.plugin")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_roots = {"subprocess", "requests", "urllib", "socket", "httpx"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    proposal = ProjectPlugin(project_resolver=_resolver()).invoke(
        "project.milestone_proposal",
        {"project_id": "考研 408", "milestone": {"title": "review"}},
        {},
    )
    assert imported_roots.isdisjoint(forbidden_roots)
    assert proposal["executed"] is False
