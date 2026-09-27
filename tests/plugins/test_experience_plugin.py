from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, load_manifests


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "04_个人领域" / "ExperienceEvent.json"
CAPABILITIES = (
    "experience.record_proposal",
    "experience.transition_proposal",
    "experience.reflection_promotion_proposal",
)


def _api():
    from capability_plugins.experience import ExperiencePlugin, ExperiencePluginError

    return ExperiencePlugin, ExperiencePluginError


def test_experience_schema_has_fixed_timeline_lifecycle():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = {item["name"]: item for item in schema["fields"]}

    assert set(fields) == {
        "experience_id",
        "title",
        "status",
        "scheduled_at",
        "reflection_ref",
        "created_at",
        "updated_at",
    }
    assert fields["status"]["options"] == [
        "wishlist",
        "planned",
        "booked",
        "experienced",
        "reflection",
    ]


def test_experience_manifest_is_dormant_and_proposal_only():
    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "experience"
    )
    assert manifest.provides == CAPABILITIES
    assert manifest.activation_state is ActivationState.DORMANT
    assert manifest.writes == ()
    assert set(manifest.capability_effects.values()) == {"proposal"}


def test_record_and_transition_follow_experience_timeline():
    ExperiencePlugin, ExperiencePluginError = _api()
    plugin = ExperiencePlugin()
    recorded = plugin.invoke(
        "experience.record_proposal",
        {"experience_id": "experience-alps", "title": "去阿尔卑斯徒步"},
        {},
    )
    assert recorded["event"]["status"] == "wishlist"

    transition = plugin.invoke(
        "experience.transition_proposal",
        {
            "experience_id": "experience-alps",
            "from_status": "wishlist",
            "to_status": "planned",
        },
        {},
    )
    assert transition["transition"] == {"from": "wishlist", "to": "planned"}
    with pytest.raises(ExperiencePluginError) as skip:
        plugin.invoke(
            "experience.transition_proposal",
            {
                "experience_id": "experience-alps",
                "from_status": "planned",
                "to_status": "experienced",
            },
            {},
        )
    assert skip.value.code == "invalid_transition"


def test_reflection_promotion_requires_explicit_confirmation():
    ExperiencePlugin, ExperiencePluginError = _api()
    plugin = ExperiencePlugin(status_reader=lambda experience_id: "reflection")
    payload = {
        "experience_id": "experience-alps",
        "reflection_ref": "KN-EXP-ALPS",
        "target_type": "experience",
    }
    with pytest.raises(ExperiencePluginError) as unconfirmed:
        plugin.invoke("experience.reflection_promotion_proposal", payload, {})
    assert unconfirmed.value.code == "explicit_confirmation_required"

    result = plugin.invoke(
        "experience.reflection_promotion_proposal",
        dict(payload, user_confirmed=True),
        {},
    )
    assert result["reflection_ref"] == "KN-EXP-ALPS"
    assert result["requires_human_review"] is True
    assert result["executed"] is False


def test_reflection_target_is_limited_to_experience_or_principle():
    ExperiencePlugin, ExperiencePluginError = _api()
    with pytest.raises(ExperiencePluginError) as invalid:
        ExperiencePlugin(status_reader=lambda experience_id: "reflection").invoke(
            "experience.reflection_promotion_proposal",
            {
                "experience_id": "experience-alps",
                "reflection_ref": "KN-EXP-ALPS",
                "target_type": "core_rule",
                "user_confirmed": True,
            },
            {},
        )
    assert invalid.value.code == "invalid_target_type"


def test_transition_rejects_unknown_fields_and_promotion_requires_reflection_state():
    ExperiencePlugin, ExperiencePluginError = _api()
    plugin = ExperiencePlugin()
    with pytest.raises(ExperiencePluginError) as extra:
        plugin.invoke(
            "experience.transition_proposal",
            {
                "experience_id": "experience-alps",
                "from_status": "wishlist",
                "to_status": "planned",
                "content": "不应被忽略",
            },
            {},
        )
    assert extra.value.code == "invalid_fields"

    state_plugin = ExperiencePlugin(status_reader=lambda experience_id: "experienced")
    with pytest.raises(ExperiencePluginError) as state:
        state_plugin.invoke(
            "experience.reflection_promotion_proposal",
            {
                "experience_id": "experience-alps",
                "reflection_ref": "KN-EXP-ALPS",
                "target_type": "experience",
                "user_confirmed": True,
            },
            {},
        )
    assert state.value.code == "reflection_state_required"

    with pytest.raises(ExperiencePluginError) as unavailable:
        plugin.invoke(
            "experience.reflection_promotion_proposal",
            {
                "experience_id": "experience-missing",
                "reflection_ref": "KN-EXP-MISSING",
                "target_type": "experience",
                "user_confirmed": True,
            },
            {},
        )
    assert unavailable.value.code == "experience_state_unavailable"
