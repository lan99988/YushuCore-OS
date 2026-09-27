from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from runtime_core.action_policy import ActionPolicy
from runtime_core.models import ActionAuthority, AgentDefinition, PlannedAction


PLUGIN_PERMISSIONS = {"records.write", "records.read", "messaging.send", "records.delete"}
AGENT_PERMISSIONS = {"records.write", "records.read", "messaging.send", "records.delete"}


def _action(**overrides) -> PlannedAction:
    values = {
        "action_id": "action-1",
        "plugin_id": "records-plugin",
        "capability": "records.write",
        "authority": ActionAuthority.AUTONOMOUS,
        "reversible": True,
        "external_effect": False,
        "affects_commitment": False,
        "risk": "low",
        "payload_digest": "a" * 64,
    }
    values.update(overrides)
    return PlannedAction(**values)


def _evaluate(action: PlannedAction, **overrides):
    values = {
        "plugin_permissions": PLUGIN_PERMISSIONS,
        "agent_permissions": AGENT_PERMISSIONS,
        "agent_autonomy_level": 2,
        "known_capabilities": PLUGIN_PERMISSIONS,
    }
    values.update(overrides)
    return ActionPolicy().evaluate(action, **values)


def test_runtime_core_exports_wp2_public_api():
    import runtime_core

    assert runtime_core.ActionPolicy is ActionPolicy
    assert runtime_core.AuditLogger.__name__ == "AuditLogger"
    assert runtime_core.AuditRecord.__name__ == "AuditRecord"
    assert runtime_core.PolicyDecision.__name__ == "PolicyDecision"


def test_read_only_action_is_allowed_without_approval():
    decision = _evaluate(
        _action(capability="records.read", authority=ActionAuthority.OBSERVE)
    )

    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.effective_authority is ActionAuthority.OBSERVE


def test_planned_action_rejects_non_sha256_payload_digest():
    with pytest.raises(ValueError, match="payload_digest"):
        _action(payload_digest="not-a-sha256-digest")


def test_reversible_internal_action_can_be_autonomous():
    decision = _evaluate(_action())

    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.effective_authority is ActionAuthority.AUTONOMOUS


def test_external_commitment_requires_approval():
    decision = _evaluate(_action(affects_commitment=True))

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.effective_authority is ActionAuthority.APPROVAL_REQUIRED
    assert decision.reason_code == "approval_required_external_commitment"


def test_external_action_cannot_use_approval_to_mask_missing_permission():
    decision = _evaluate(
        _action(affects_commitment=True, required_permissions=("records.write",)),
        plugin_permissions=set(),
        agent_permissions=set(),
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.reason_code == "plugin_permission_denied"


def test_external_message_requires_approval():
    decision = _evaluate(
        _action(
            capability="messaging.send",
            operation="send_message",
            external_effect=True,
        )
    )

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.effective_authority is ActionAuthority.APPROVAL_REQUIRED
    assert decision.reason_code == "approval_required_external_message"


def test_payment_requires_approval():
    decision = _evaluate(_action(operation="payment"))

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.reason_code == "approval_required_payment"


def test_irreversible_delete_requires_approval():
    decision = _evaluate(
        _action(
            capability="records.delete",
            operation="delete",
            reversible=False,
        )
    )

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.effective_authority is ActionAuthority.APPROVAL_REQUIRED
    assert decision.reason_code == "approval_required_irreversible"


def test_unknown_action_defaults_to_suggest():
    decision = _evaluate(
        _action(
            capability="unknown.execute",
            required_permissions=("unknown.execute",),
        ),
        plugin_permissions={"unknown.execute"},
        agent_permissions={"unknown.execute"},
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.effective_authority is ActionAuthority.SUGGEST
    assert decision.reason_code == "unknown_action_suggest"


def test_permissions_are_checked_before_unknown_action_fallback():
    decision = _evaluate(
        _action(risk="unknown", required_permissions=("ungranted.permission",)),
        plugin_permissions=set(),
        agent_permissions=set(),
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.reason_code == "plugin_permission_denied"


def test_agent_autonomy_level_is_not_raised_for_approval_flow():
    agent = AgentDefinition(
        agent_id="agent-1",
        name="Test Agent",
        domain="test",
        autonomy_level=2,
        risk_level="low",
        permissions=("records.write",),
        handler=lambda context: None,
    )

    decision = _evaluate(
        _action(external_effect=True),
        agent_autonomy_level=agent.autonomy_level,
    )

    assert decision.approval_required is True
    assert decision.effective_authority is ActionAuthority.APPROVAL_REQUIRED
    assert agent.autonomy_level == 2


def test_prohibition_takes_precedence_over_approval_and_permissions():
    decision = _evaluate(
        _action(external_effect=True, affects_commitment=True),
        prohibited=True,
        plugin_permissions=set(),
        agent_permissions=set(),
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.effective_authority is ActionAuthority.SUGGEST
    assert decision.reason_code == "action_prohibited"


@pytest.mark.parametrize(
    ("plugin_permissions", "agent_permissions", "reason_code"),
    [
        (set(), AGENT_PERMISSIONS, "plugin_permission_denied"),
        (PLUGIN_PERMISSIONS, set(), "agent_permission_denied"),
    ],
)
def test_both_plugin_and_agent_permissions_are_required(
    plugin_permissions, agent_permissions, reason_code
):
    decision = _evaluate(
        _action(required_permissions=("records.write",)),
        plugin_permissions=plugin_permissions,
        agent_permissions=agent_permissions,
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.effective_authority is ActionAuthority.SUGGEST
    assert decision.reason_code == reason_code


def test_low_agent_autonomy_does_not_gain_autonomous_authority():
    decision = _evaluate(_action(), agent_autonomy_level=1)

    assert decision.allowed is False
    assert decision.effective_authority is ActionAuthority.SUGGEST
    assert decision.reason_code == "agent_autonomy_insufficient"


def test_policy_rejects_agent_autonomy_above_system_ceiling():
    decision = _evaluate(_action(), agent_autonomy_level=3)

    assert decision.allowed is False
    assert decision.effective_authority is ActionAuthority.SUGGEST
    assert decision.reason_code == "agent_autonomy_exceeds_system_ceiling"


def test_permission_config_keeps_defaults_and_declares_prohibitions_and_approvals():
    config = yaml.safe_load(
        (Path(__file__).parents[1] / "config" / "permission.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert config["default"] == "deny"
    assert config["agent_direct_vault_access"] is False
    assert config["agent_direct_external_api"] is False
    assert config["personal_memory_agent_write"] is False
    assert {"direct_vault_access", "direct_external_api"} <= set(
        config["prohibited_actions"]
    )
    assert {
        "external_commitment",
        "payment",
        "external_message",
        "irreversible_delete",
    } <= set(config["human_approval_required_for"])


def test_action_policy_from_permission_config_enforces_declared_prohibition():
    config_path = Path(__file__).parents[1] / "config" / "permission.yaml"
    policy = ActionPolicy.from_file(config_path)

    decision = policy.evaluate(
        _action(operation="direct_vault_access"),
        plugin_permissions=PLUGIN_PERMISSIONS,
        agent_permissions=AGENT_PERMISSIONS,
        agent_autonomy_level=2,
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.reason_code == "action_prohibited"


def test_action_policy_from_permission_config_enforces_declared_approval():
    config_path = Path(__file__).parents[1] / "config" / "permission.yaml"
    policy = ActionPolicy.from_file(config_path)
    action = _action(operation="knowledge_change")

    decision = policy.evaluate(
        action,
        plugin_permissions=PLUGIN_PERMISSIONS,
        agent_permissions=AGENT_PERMISSIONS,
        agent_autonomy_level=2,
        known_capabilities=PLUGIN_PERMISSIONS,
    )

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.reason_code == "approval_required_configured_action"


@pytest.mark.parametrize(
    "unsafe_config",
    [
        "default: allow\nagent_direct_vault_access: false\nagent_direct_external_api: false\npersonal_memory_agent_write: false\n",
        "default: deny\nagent_direct_vault_access: true\nagent_direct_external_api: false\npersonal_memory_agent_write: false\n",
        "default: deny\nagent_direct_vault_access: false\nagent_direct_external_api: true\npersonal_memory_agent_write: false\n",
        "default: deny\nagent_direct_vault_access: false\nagent_direct_external_api: false\npersonal_memory_agent_write: true\n",
    ],
)
def test_action_policy_rejects_unsafe_permission_defaults(tmp_path, unsafe_config):
    path = tmp_path / "permission.yaml"
    path.write_text(unsafe_config, encoding="utf-8")

    with pytest.raises(ValueError, match="default deny|must remain false"):
        ActionPolicy.from_file(path)


@pytest.mark.parametrize(
    "missing_or_empty_field",
    [
        ("prohibited_actions", None),
        ("prohibited_actions", []),
        ("human_approval_required_for", None),
        ("human_approval_required_for", []),
    ],
)
def test_action_policy_rejects_missing_or_empty_safety_rule_lists(
    tmp_path, missing_or_empty_field
):
    field_name, replacement = missing_or_empty_field
    config = {
        "default": "deny",
        "agent_direct_vault_access": False,
        "agent_direct_external_api": False,
        "personal_memory_agent_write": False,
        "prohibited_actions": ["direct_vault_access"],
        "human_approval_required_for": ["payment"],
    }
    if replacement is None:
        config.pop(field_name)
    else:
        config[field_name] = replacement
    path = tmp_path / "permission.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match=field_name):
        ActionPolicy.from_file(path)
