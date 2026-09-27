from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, load_manifests


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "04_个人领域" / "InterestTopic.json"
CAPABILITIES = (
    "interest.record_proposal",
    "interest.exploration_proposal",
    "interest.project_conversion_proposal",
    "interest.review",
)


def _api():
    from capability_plugins.interest import InterestPlugin, InterestPluginError

    return InterestPlugin, InterestPluginError


def test_interest_schema_has_no_kpi_streak_or_target_fields():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = {item["name"] for item in schema["fields"]}

    assert fields == {
        "interest_id",
        "title",
        "knowledge_ref",
        "last_explored_at",
        "created_at",
        "updated_at",
    }
    assert not fields & {"kpi", "target", "streak", "score", "deadline"}


def test_interest_manifest_is_dormant_with_proposals_and_read_only_review():
    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "interest"
    )
    assert manifest.provides == CAPABILITIES
    assert manifest.activation_state is ActivationState.DORMANT
    assert manifest.activation_mode == "on_demand"
    assert manifest.writes == ()
    assert manifest.capability_effects["interest.review"] == "read_only"
    assert {
        effect
        for capability, effect in manifest.capability_effects.items()
        if capability != "interest.review"
    } == {"proposal"}


def test_record_and_lightweight_exploration_are_optional_proposals():
    InterestPlugin, _ = _api()
    plugin = InterestPlugin()

    recorded = plugin.invoke(
        "interest.record_proposal",
        {"interest_id": "interest-space", "title": "天文学"},
        {},
    )
    explored = plugin.invoke(
        "interest.exploration_proposal",
        {
            "interest_id": "interest-space",
            "summary": "了解了木星大红斑",
            "observed_at": "2026-09-27",
        },
        {},
    )

    assert recorded["topic"] == {"interest_id": "interest-space", "title": "天文学"}
    assert explored["event"]["summary"] == "了解了木星大红斑"
    assert all(item["executed"] is False for item in (recorded, explored))


def test_project_conversion_requires_an_explicit_user_request():
    InterestPlugin, InterestPluginError = _api()
    plugin = InterestPlugin()

    with pytest.raises(InterestPluginError) as implicit:
        plugin.invoke(
            "interest.project_conversion_proposal",
            {"interest_id": "interest-space", "project_title": "观星计划"},
            {},
        )
    assert implicit.value.code == "explicit_request_required"

    result = plugin.invoke(
        "interest.project_conversion_proposal",
        {
            "interest_id": "interest-space",
            "project_title": "观星计划",
            "user_requested": True,
        },
        {},
    )
    assert result["project_title"] == "观星计划"
    assert result["requires_human_review"] is True


def test_interest_rejects_metrics_and_unknown_capabilities():
    InterestPlugin, InterestPluginError = _api()
    plugin = InterestPlugin()

    with pytest.raises(InterestPluginError) as metric:
        plugin.invoke(
            "interest.record_proposal",
            {"interest_id": "interest-space", "title": "天文学", "kpi": 3},
            {},
        )
    assert metric.value.code == "invalid_fields"
    with pytest.raises(InterestPluginError) as unknown:
        plugin.invoke("interest.enforce_streak", {}, {})
    assert unknown.value.code == "unsupported_capability"
