from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from capability_plugins import ActivationState, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
EXPECTED_CAPABILITIES = (
    "learning.current_state",
    "learning.progress",
    "learning.context",
)


def _api():
    from capability_plugins.learning import LearningPlugin, LearningPluginError

    return LearningPlugin, LearningPluginError


def _manifest():
    return next(
        item
        for item in load_manifests(MANIFEST_DIR)
        if item.plugin_id == "learning"
    )


def test_learning_manifest_declares_only_read_only_learning_capabilities():
    manifest = _manifest()

    assert manifest.domain == "learning"
    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.permissions == ("read_knowledge",)
    assert set(manifest.capability_permissions) == set(EXPECTED_CAPABILITIES)
    assert all(
        manifest.capability_permissions[capability] == ("read_knowledge",)
        for capability in EXPECTED_CAPABILITIES
    )
    assert set(manifest.capability_effects) == set(EXPECTED_CAPABILITIES)
    assert set(manifest.capability_effects.values()) == {"read_only"}
    assert manifest.activation_mode == "on_demand"
    assert manifest.activation_state is ActivationState.DORMANT


def test_learning_capabilities_delegate_read_only_and_return_detached_data():
    LearningPlugin, _ = _api()
    cached = {
        "learning.current_state": {"active_goal": "algebra", "topics": ["linear"]},
        "learning.progress": {"completed": 4, "target": 8},
        "learning.context": {"knowledge": [{"id": "K-1"}]},
    }
    calls = []
    delegates = {
        capability: (lambda payload, capability=capability: (
            calls.append((capability, deepcopy(payload))), cached[capability]
        )[1])
        for capability in EXPECTED_CAPABILITIES
    }
    plugin = LearningPlugin(delegates=delegates)
    payload = {"range": "this_week", "filters": {"domain": "math"}}

    results = {
        capability: plugin.invoke(capability, payload, {"agent_id": "study_agent"})
        for capability in EXPECTED_CAPABILITIES
    }
    results["learning.current_state"]["topics"].append("caller-edit")

    assert calls == [(capability, payload) for capability in EXPECTED_CAPABILITIES]
    assert results["learning.progress"] == cached["learning.progress"]
    assert cached["learning.current_state"]["topics"] == ["linear"]
    assert plugin.manifest.writes == ()


def test_missing_learning_source_fails_closed_with_stable_error():
    LearningPlugin, LearningPluginError = _api()
    plugin = LearningPlugin()

    with pytest.raises(LearningPluginError) as error:
        plugin.invoke("learning.progress", {"range": "week"}, {})

    assert error.value.code == "learning_source_unavailable"
    assert "learning_source_unavailable" == str(error.value)


def test_learning_delegate_failure_is_sanitized_and_does_not_chain_private_error():
    LearningPlugin, LearningPluginError = _api()

    def broken(_payload):
        raise RuntimeError("private learning record contents")

    plugin = LearningPlugin(delegates={"learning.context": broken})

    with pytest.raises(LearningPluginError) as error:
        plugin.invoke("learning.context", {"topic": "math"}, {})

    assert error.value.code == "learning_source_failed"
    assert "private learning record contents" not in str(error.value)
    assert error.value.__cause__ is None


def test_learning_plugin_rejects_bad_delegates_payloads_and_unknown_capability():
    LearningPlugin, LearningPluginError = _api()
    plugin = LearningPlugin(delegates={"learning.current_state": lambda payload: payload})

    with pytest.raises(ValueError):
        LearningPlugin(delegates={"learning.plan": lambda payload: payload})
    with pytest.raises(TypeError):
        LearningPlugin(delegates={"learning.progress": "not-callable"})
    with pytest.raises(LearningPluginError) as invalid:
        plugin.invoke("learning.current_state", [], {})
    assert invalid.value.code == "invalid_payload"
    with pytest.raises(LearningPluginError) as unknown:
        plugin.invoke("learning.delete", {}, {})
    assert unknown.value.code == "unsupported_capability"
