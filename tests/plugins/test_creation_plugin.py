from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, load_manifests


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "04_个人领域" / "CreationItem.json"
CAPABILITIES = (
    "creation.capture_proposal",
    "creation.transition_proposal",
    "creation.feedback_proposal",
)


def _api():
    from capability_plugins.creation import CreationPlugin, CreationPluginError

    return CreationPlugin, CreationPluginError


def test_creation_schema_is_minimal_and_uses_a_knowledge_pointer():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = {item["name"]: item for item in schema["fields"]}

    assert set(fields) == {
        "creation_id",
        "title",
        "status",
        "knowledge_ref",
        "feedback_summary",
        "created_at",
        "updated_at",
    }
    assert fields["status"]["options"] == [
        "idea",
        "draft",
        "production",
        "publish",
        "feedback",
        "archive",
    ]
    assert "content" not in fields and "body" not in fields


def test_creation_manifest_is_dormant_and_proposal_only():
    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "creation"
    )

    assert manifest.provides == CAPABILITIES
    assert manifest.activation_state is ActivationState.DORMANT
    assert manifest.activation_mode == "on_demand"
    assert manifest.writes == ()
    assert set(manifest.capability_effects.values()) == {"proposal"}


def test_capture_idea_keeps_long_content_out_and_requires_review():
    CreationPlugin, _ = _api()
    plugin = CreationPlugin()

    result = plugin.invoke(
        "creation.capture_proposal",
        {
            "creation_id": "creation-1",
            "title": "写一篇个人系统文章",
            "knowledge_ref": "KN-CREATION-1",
        },
        {},
    )

    assert result["item"]["status"] == "idea"
    assert result["item"]["knowledge_ref"] == "KN-CREATION-1"
    assert "content" not in result["item"]
    assert result["status"] == "pending_human_review"
    assert result["executed"] is False


def test_transition_follows_fixed_lifecycle_and_cannot_skip():
    CreationPlugin, CreationPluginError = _api()
    plugin = CreationPlugin()

    result = plugin.invoke(
        "creation.transition_proposal",
        {"creation_id": "creation-1", "from_status": "idea", "to_status": "draft"},
        {},
    )
    assert result["transition"] == {"from": "idea", "to": "draft"}

    with pytest.raises(CreationPluginError) as invalid:
        plugin.invoke(
            "creation.transition_proposal",
            {"creation_id": "creation-1", "from_status": "idea", "to_status": "publish"},
            {},
        )
    assert invalid.value.code == "invalid_transition"

    with pytest.raises(CreationPluginError) as extra:
        plugin.invoke(
            "creation.transition_proposal",
            {
                "creation_id": "creation-1",
                "from_status": "idea",
                "to_status": "draft",
                "content": "正文不应被静默忽略",
            },
            {},
        )
    assert extra.value.code == "invalid_fields"


def test_feedback_is_summary_only_and_errors_are_sanitized():
    CreationPlugin, CreationPluginError = _api()
    plugin = CreationPlugin()
    result = plugin.invoke(
        "creation.feedback_proposal",
        {"creation_id": "creation-1", "feedback_summary": "读者希望增加示例"},
        {},
    )
    assert result["feedback_summary"] == "读者希望增加示例"
    assert result["status"] == "pending_human_review"

    with pytest.raises(CreationPluginError) as unknown:
        plugin.invoke("creation.publish_now", {}, {})
    assert unknown.value.code == "unsupported_capability"
