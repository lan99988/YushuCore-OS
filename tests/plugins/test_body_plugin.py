from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agents.body_advisor import assess_body_snapshot
from capability_plugins import ActivationState, PluginRegistry, load_manifests
from capability_plugins.body.plugin import BodyPlugin, BodyPluginError


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "capability_plugins" / "manifests" / "body.yaml"


@pytest.fixture
def body_snapshot() -> dict[str, object]:
    return {
        "source": "garmin",
        "date_range": {"start": "2026-09-01", "end": "2026-09-25"},
        "today_energy_context": {
            "date": "2026-09-24",
            "requested_date": "2026-09-25",
            "is_requested_date": False,
            "body_battery_score": 18,
            "sleep_hours": 5.5,
            "stress_level": 68,
            "mental_state": "depleted",
            "study_load": "recovery",
            "source": "garmin",
            "metadata": {"labels": ["latest-valid-day"]},
        },
        "today_training_context": {
            "date": "2026-09-25",
            "training_load": "deload",
            "training_load_label": "降载",
            "recommendation": "恢复优先",
            "warnings": [{"code": "strength_3d_streak"}],
        },
        "training_load_trend": "increasing",
        "recovery_trend": "declining",
        "energy_daily": [{"date": "2026-09-24", "body_battery_score": 18}],
        "training_logs": [],
    }


def test_manifest_declares_only_read_only_body_capabilities():
    manifest = next(
        item for item in load_manifests(MANIFEST_PATH.parent) if item.plugin_id == "body"
    )

    assert manifest.provides == (
        "body.current_energy",
        "body.recovery_context",
        "body.training_context",
        "body.adjustment_suggestion",
    )
    assert manifest.reads
    assert manifest.writes == ()
    assert "read_body_snapshot" in manifest.permissions
    assert manifest.activation_state is ActivationState.DORMANT


def test_current_energy_returns_latest_precomputed_garmin_context(body_snapshot):
    plugin = BodyPlugin()

    result = plugin.invoke(
        "body.current_energy", {"snapshot": body_snapshot}, {"agent_id": "test"}
    )

    assert result == body_snapshot["today_energy_context"]
    assert result["date"] == "2026-09-24"
    assert result["is_requested_date"] is False
    assert result["source"] == "garmin"


def test_returned_context_is_detached_from_the_read_only_snapshot(body_snapshot):
    plugin = BodyPlugin()

    result = plugin.invoke(
        "body.current_energy", {"snapshot": body_snapshot}, {"agent_id": "test"}
    )
    result["metadata"]["labels"].append("caller-edit")

    assert body_snapshot["today_energy_context"]["metadata"]["labels"] == [
        "latest-valid-day"
    ]


def test_training_and_recovery_context_reuse_existing_pure_policies(body_snapshot):
    plugin = BodyPlugin()

    training = plugin.invoke(
        "body.training_context", {"snapshot": body_snapshot}, {"agent_id": "test"}
    )
    recovery = plugin.invoke(
        "body.recovery_context", {"snapshot": body_snapshot}, {"agent_id": "test"}
    )

    assert training == body_snapshot["today_training_context"]
    assert recovery["recovery_state"] == "protect"
    assert recovery["recommended_training"] == "recovery"
    assert {item["code"] for item in recovery["warnings"]} == {
        "low_body_energy",
        "low_sleep",
        "high_stress",
        "training_risk",
    }


def test_adjustment_suggestion_matches_legacy_assessor_core_fields(body_snapshot):
    plugin = BodyPlugin()

    result = plugin.invoke(
        "body.adjustment_suggestion",
        {"snapshot": body_snapshot},
        {"agent_id": "test"},
    )

    assert result == assess_body_snapshot(body_snapshot)
    assert result["recommended_load"] == "reduce"
    assert result["requires_human_review"] is True
    assert result["status"] == "draft"


def test_explicit_snapshot_reader_is_used_without_mutating_or_writing(body_snapshot):
    calls = []

    def reader():
        calls.append("read")
        return body_snapshot

    plugin = BodyPlugin(snapshot_reader=reader)
    result = plugin.invoke(
        "body.current_energy", {}, {"agent_id": "test"}
    )

    assert calls == ["read"]
    assert result["body_battery_score"] == 18
    assert plugin.manifest.writes == ()
    assert not any(hasattr(plugin, name) for name in ("write", "save", "sync", "fetch"))


def test_snapshot_reader_exceptions_are_safely_mapped():
    def broken_reader():
        raise RuntimeError("sensitive source details")

    plugin = BodyPlugin(snapshot_reader=broken_reader)

    with pytest.raises(BodyPluginError) as error:
        plugin.invoke("body.current_energy", {}, {"agent_id": "test"})

    assert error.value.code == "snapshot_unavailable"
    assert "sensitive source details" not in str(error.value)
    assert error.value.__cause__ is None


def test_invalid_input_and_unknown_capability_have_stable_errors():
    plugin = BodyPlugin()

    with pytest.raises(BodyPluginError) as missing:
        plugin.invoke("body.current_energy", {}, {"agent_id": "test"})
    assert missing.value.code == "snapshot_required"

    with pytest.raises(BodyPluginError) as invalid:
        plugin.invoke("body.current_energy", {"snapshot": []}, {"agent_id": "test"})
    assert invalid.value.code == "invalid_snapshot"

    with pytest.raises(BodyPluginError) as unknown:
        plugin.invoke("body.private_capability", {"snapshot": {}}, {"agent_id": "test"})
    assert unknown.value.code == "unsupported_capability"


def test_disabling_plugin_does_not_change_legacy_assessor(body_snapshot):
    manifest = next(
        item for item in load_manifests(MANIFEST_PATH.parent) if item.plugin_id == "body"
    )
    disabled_registry = PluginRegistry.from_manifests(
        [replace(manifest, enabled=False, activation_state=ActivationState.DORMANT)]
    )

    assert disabled_registry.explain("body")["status"] == "disabled"
    with pytest.raises(LookupError):
        disabled_registry.by_capability("body.adjustment_suggestion")
    assert assess_body_snapshot(body_snapshot)["recommended_load"] == "reduce"
