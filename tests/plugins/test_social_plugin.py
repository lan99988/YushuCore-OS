from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, Availability, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
SCHEMA_DIR = ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "04_个人领域"
EXPECTED_CAPABILITIES = ("social.capture",)
CAPTURE_TEXT = "昨天和小王吃饭，他准备年底换工作；我答应周末发简历模板。"


def _api():
    try:
        spec = importlib.util.find_spec("capability_plugins.social.plugin")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "capability_plugins.social.plugin is required"
    module = importlib.import_module("capability_plugins.social.plugin")
    return module.SocialPlugin, module.SocialPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "social"
    )


def test_social_manifest_is_on_demand_dormant_and_proposal_only():
    SocialPlugin, _ = _api()
    manifest = _manifest()

    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.capability_permissions == {"social.capture": ("propose_change",)}
    assert manifest.capability_effects == {"social.capture": "proposal"}
    assert "propose_change" in manifest.permissions
    assert manifest.availability is Availability.INSTALLED
    assert manifest.activation_mode == "on_demand"
    assert manifest.enabled is True
    assert manifest.activation_state is ActivationState.DORMANT
    assert SocialPlugin().manifest == manifest


def test_social_schemas_define_only_person_interaction_and_commitment():
    expected = {
        "SocialPerson.json": "SocialPerson",
        "SocialInteraction.json": "SocialInteraction",
        "SocialCommitment.json": "SocialCommitment",
    }
    assert {path.name for path in SCHEMA_DIR.glob("Social*.json")} >= set(expected)

    for filename, title in expected.items():
        schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["title"] == title
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

    person = json.loads((SCHEMA_DIR / "SocialPerson.json").read_text(encoding="utf-8"))
    assert set(person["properties"]) == {
        "person_id", "name", "relationship", "last_contact_at", "next_attention", "open_commitments"
    }
    assert {"person_id", "name", "relationship"} <= set(person["required"])

    interaction = json.loads((SCHEMA_DIR / "SocialInteraction.json").read_text(encoding="utf-8"))
    assert set(interaction["properties"]) == {
        "interaction_id", "person_id", "occurred_at", "activity", "context", "source_ref"
    }
    assert {"person_id", "occurred_at", "context"} <= set(interaction["required"])

    commitment = json.loads((SCHEMA_DIR / "SocialCommitment.json").read_text(encoding="utf-8"))
    assert "external_action" in commitment["properties"]
    assert commitment["properties"]["external_action"]["properties"]["requires_human_review"] == {"const": True}
    assert commitment["properties"]["external_action"]["properties"]["executed"] == {"const": False}
    assert set(expected) == {path.name for path in SCHEMA_DIR.glob("Social*.json")}


def test_one_natural_capture_builds_minimal_person_interaction_context_and_commitment_proposal():
    SocialPlugin, _ = _api()
    plugin = SocialPlugin()

    result = plugin.invoke(
        "social.capture",
        {"text": CAPTURE_TEXT, "captured_at": "2026-09-27T12:00:00+08:00"},
        {},
    )

    assert result["proposal_type"] == "social_capture"
    assert result["person"]["name"] == "小王"
    assert result["person"]["relationship"] == "unspecified"
    assert result["person"]["last_contact_at"] == "2026-09-26T12:00:00+08:00"
    assert set(result["person"]) <= {
        "person_id", "name", "relationship", "last_contact_at", "next_attention", "open_commitments"
    }
    assert result["interaction"]["person_id"] == result["person"]["person_id"]
    assert result["interaction"]["activity"] == "吃饭"
    assert result["interaction"]["context"] == ["小王准备年底换工作"]
    assert result["commitment"]["person_id"] == result["person"]["person_id"]
    assert result["commitment"]["action"] == "发简历模板"
    assert result["commitment"]["due_text"] == "周末"
    assert result["commitment"]["due_at"] is None
    assert result["commitment"]["external_action"]["requires_human_review"] is True
    assert result["commitment"]["external_action"]["executed"] is False
    assert result["commitment"]["external_action"]["approval"]["status"] == "pending_human_review"
    assert result["executed"] is False
    assert result["requires_human_review"] is True
    assert "contacts" not in result
    assert "contact_table" not in result


def test_social_capture_rejects_ambiguous_people_and_malformed_timestamp_safely():
    SocialPlugin, SocialPluginError = _api()
    plugin = SocialPlugin()

    with pytest.raises(SocialPluginError) as missing_person:
        plugin.invoke("social.capture", {"text": "我答应周末发简历模板。"}, {})
    assert missing_person.value.error_code == "person_not_identified"

    with pytest.raises(SocialPluginError) as invalid_time:
        plugin.invoke(
            "social.capture",
            {"text": CAPTURE_TEXT, "captured_at": "yesterday"},
            {},
        )
    assert invalid_time.value.error_code == "invalid_input"


def test_social_capture_uses_an_injected_clock_when_user_only_provides_text():
    from datetime import datetime

    SocialPlugin, _ = _api()
    fixed_now = datetime.fromisoformat("2026-09-27T12:00:00+08:00")

    result = SocialPlugin(clock=lambda: fixed_now).invoke(
        "social.capture", {"text": CAPTURE_TEXT}, {}
    )

    assert result["captured_at"] == "2026-09-27T12:00:00+08:00"
    assert result["interaction"]["occurred_at"] == "2026-09-26T12:00:00+08:00"


@pytest.mark.parametrize(
    "text",
    (
        "和小王吃饭，他准备" + "换" * 500,
        "和小王吃饭；我答应" + "发" * 300,
    ),
)
def test_social_capture_rejects_values_that_cannot_satisfy_its_schemas(text):
    SocialPlugin, SocialPluginError = _api()

    with pytest.raises(SocialPluginError) as invalid_value:
        SocialPlugin().invoke(
            "social.capture",
            {"text": text, "captured_at": "2026-09-27T12:00:00+08:00"},
            {},
        )

    assert invalid_value.value.error_code == "invalid_input"


def test_social_errors_are_stable_and_only_the_capture_capability_is_exposed():
    SocialPlugin, SocialPluginError = _api()

    with pytest.raises(SocialPluginError) as capability_error:
        SocialPlugin().invoke("social.person.list", {}, {})
    assert capability_error.value.error_code == "unsupported_capability"

    with pytest.raises(SocialPluginError) as input_error:
        SocialPlugin().invoke("social.capture", {"text": "private text", "extra": "secret"}, {})
    assert input_error.value.error_code == "invalid_input"
    assert "secret" not in str(input_error.value)
