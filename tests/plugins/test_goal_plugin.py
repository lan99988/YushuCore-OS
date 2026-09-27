from __future__ import annotations

import ast
from dataclasses import asdict, replace
import importlib
import importlib.util
from pathlib import Path

import pytest

from capability_plugins import ActivationState, Availability, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
EXPECTED_CAPABILITIES = (
    "goal.parse",
    "goal.current",
    "goal.gap",
    "goal.create_proposal",
)


def _api():
    try:
        spec = importlib.util.find_spec("capability_plugins.goal.plugin")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "capability_plugins.goal.plugin is required"
    module = importlib.import_module("capability_plugins.goal.plugin")
    return module.GoalPlugin, module.GoalPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "goal"
    )


def _goal():
    from personal_intelligence.models import Goal

    return Goal(
        goal_type="career",
        title="完成职业资格认证",
        priority="high",
        status="active",
        related_domains=("study", "project"),
    )


def test_goal_manifest_and_adapter_have_complete_on_demand_policy_metadata():
    GoalPlugin, _ = _api()
    manifest = _manifest()

    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.capability_permissions.keys() == set(EXPECTED_CAPABILITIES)
    assert manifest.capability_effects.keys() == set(EXPECTED_CAPABILITIES)
    assert {"read_goal", "propose_change"} <= set(manifest.permissions)
    assert manifest.capability_permissions["goal.create_proposal"] == ("propose_change",)
    assert manifest.capability_effects["goal.create_proposal"] == "proposal"
    assert manifest.availability is Availability.INSTALLED
    assert manifest.activation_mode == "on_demand"
    assert manifest.enabled is True
    assert manifest.activation_state is ActivationState.DORMANT
    assert GoalPlugin().manifest == manifest


def test_goal_parse_validates_and_returns_existing_goal_model():
    GoalPlugin, _ = _api()

    result = GoalPlugin().invoke("goal.parse", {"goal": asdict(_goal())}, {})

    assert result == asdict(_goal())
    assert result["related_domains"] == ("study", "project")


def test_goal_parse_accepts_a_minimal_plan_goal_without_inventing_priority():
    GoalPlugin, _ = _api()

    result = GoalPlugin().invoke(
        "goal.parse", {"goal": {"title": "提升英语能力"}}, {}
    )

    assert result == {
        "goal_type": "unspecified",
        "title": "提升英语能力",
        "priority": "unspecified",
        "status": "proposed",
        "related_domains": (),
    }


def test_goal_current_reads_existing_personal_intelligence_snapshot():
    GoalPlugin, _ = _api()
    from personal_intelligence.models import GoalModel, SelfModelSnapshot

    goal = _goal()
    snapshot = replace(
        SelfModelSnapshot.empty(),
        goals=GoalModel(goals=(goal,)),
    )
    plugin = GoalPlugin(snapshot_provider=lambda: snapshot)

    result = plugin.invoke("goal.current", {}, {})

    assert result == {"goals": [asdict(goal)]}


def test_goal_gap_delegates_analysis_without_copying_domain_algorithm():
    GoalPlugin, _ = _api()
    from personal_intelligence.models import GoalModel, SelfModelSnapshot

    current = _goal()
    snapshot = replace(
        SelfModelSnapshot.empty(),
        goals=GoalModel(goals=(current,)),
    )
    requested = {
        "goal_type": "career",
        "title": "取得证书",
        "priority": "high",
        "status": "active",
        "related_domains": ["study"],
    }
    calls = []

    def analyze_gap(target, current_goals):
        calls.append((target, current_goals))
        return {"gaps": ["尚未完成考试"], "confidence": 0.8}

    plugin = GoalPlugin(
        snapshot_provider=lambda: snapshot,
        gap_analyzer=analyze_gap,
    )
    result = plugin.invoke("goal.gap", {"goal": requested}, {})

    assert result == {"gaps": ["尚未完成考试"], "confidence": 0.8}
    assert calls[0][0].title == "取得证书"
    assert calls[0][1] == (current,)


def test_goal_create_proposal_reuses_goal_execution_port_without_approval():
    GoalPlugin, _ = _api()
    builder = importlib.import_module("personal_intelligence.execution").GoalExecutionPort
    plugin = GoalPlugin()
    payload = {"goal_id": "goal-408", "title": "完成 408 第一轮"}

    result = plugin.invoke("goal.create_proposal", payload, {})

    assert result == builder().task_proposal(
        goal_id=payload["goal_id"],
        title=payload["title"],
        approved=False,
    )
    assert result["status"] == "pending_human_review"
    assert result["execution"] is False
    assert result["requires_human_review"] is True


def test_goal_errors_are_stable_and_do_not_leak_provider_details():
    GoalPlugin, GoalPluginError = _api()
    plugin = GoalPlugin(snapshot_provider=lambda: (_ for _ in ()).throw(RuntimeError("private snapshot")))

    with pytest.raises(GoalPluginError) as current_error:
        plugin.invoke("goal.current", {}, {})
    assert current_error.value.error_code == "goal_current_failed"
    assert "private snapshot" not in str(current_error.value)
    assert current_error.value.__cause__ is None

    with pytest.raises(GoalPluginError) as input_error:
        GoalPlugin().invoke("goal.parse", {"goal": {"title": " "}}, {})
    assert input_error.value.error_code == "invalid_input"

    with pytest.raises(GoalPluginError) as capability_error:
        GoalPlugin().invoke("goal.delete", {}, {})
    assert capability_error.value.error_code == "unsupported_capability"


def test_goal_plugin_has_no_direct_network_or_file_write_imports():
    GoalPlugin, _ = _api()
    module = importlib.import_module("capability_plugins.goal.plugin")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_roots = {"subprocess", "requests", "urllib", "socket", "httpx"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    proposal = GoalPlugin().invoke(
        "goal.create_proposal",
        {"goal_id": "goal-1", "title": "prepare"},
        {},
    )
    assert imported_roots.isdisjoint(forbidden_roots)
    assert proposal["execution"] is False
