from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from runtime_core.models import ActionAuthority, PlannedAction, PolicyDecision


_KNOWN_RISK_LEVELS = frozenset({"low", "medium", "high"})
_PAYMENT_OPERATIONS = frozenset({"pay", "payment", "make_payment"})
_MESSAGE_OPERATIONS = frozenset({"message", "send_message", "send_email", "send_sms"})
_DELETE_OPERATIONS = frozenset({"delete", "remove", "destroy"})


class ActionPolicy:
    """Apply conservative, deterministic execution authority to planned actions."""

    def __init__(
        self,
        *,
        prohibited_actions: Iterable[str] = (),
        approval_required_for: Iterable[str] = (),
    ) -> None:
        self.prohibited_actions = frozenset(
            str(item).strip().lower() for item in prohibited_actions if str(item).strip()
        )
        self.approval_required_for = frozenset(
            str(item).strip().lower()
            for item in approval_required_for
            if str(item).strip()
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "ActionPolicy":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("permission config must be a mapping")
        if payload.get("default") != "deny":
            raise ValueError("permission policy must keep default deny")
        for field_name in (
            "agent_direct_vault_access",
            "agent_direct_external_api",
            "personal_memory_agent_write",
        ):
            if payload.get(field_name) is not False:
                raise ValueError(f"{field_name} must remain false")
        prohibited = payload.get("prohibited_actions")
        approvals = payload.get("human_approval_required_for")
        if not isinstance(prohibited, list) or not prohibited or not all(
            isinstance(item, str) and item.strip() for item in prohibited
        ):
            raise ValueError("prohibited_actions must be a non-empty list of strings")
        if not isinstance(approvals, list) or not approvals or not all(
            isinstance(item, str) and item.strip() for item in approvals
        ):
            raise ValueError(
                "human_approval_required_for must be a non-empty list of strings"
            )
        return cls(
            prohibited_actions=prohibited,
            approval_required_for=approvals,
        )

    def evaluate(
        self,
        action: PlannedAction,
        plugin_permissions: Iterable[str],
        agent_permissions: Iterable[str],
        agent_autonomy_level: int,
        known_capabilities: Iterable[str] | None = None,
        prohibited: bool = False,
    ) -> PolicyDecision:
        if not isinstance(action, PlannedAction):
            raise TypeError("action must be a PlannedAction")

        operation = action.operation.strip().lower()
        capability = action.capability.strip().lower()
        if (
            prohibited
            or operation in self.prohibited_actions
            or capability in self.prohibited_actions
        ):
            return self._decision(
                False,
                False,
                "action_prohibited",
                "This action is prohibited by policy and cannot be approved here.",
                ActionAuthority.SUGGEST,
            )

        required = action.required_permissions
        plugin_grants = set(plugin_permissions)
        agent_grants = set(agent_permissions)
        if any(permission not in plugin_grants for permission in required):
            return self._decision(
                False,
                False,
                "plugin_permission_denied",
                "The plugin manifest does not grant every permission required by this action.",
                ActionAuthority.SUGGEST,
            )
        if any(permission not in agent_grants for permission in required):
            return self._decision(
                False,
                False,
                "agent_permission_denied",
                "The agent does not hold every permission required by this action.",
                ActionAuthority.SUGGEST,
            )

        if type(agent_autonomy_level) is not int or not 0 <= agent_autonomy_level <= 4:
            return self._suggest("agent_autonomy_unknown")
        if agent_autonomy_level > 2:
            return self._suggest("agent_autonomy_exceeds_system_ceiling")

        if known_capabilities is not None and action.capability not in set(
            known_capabilities
        ):
            return self._suggest("unknown_action_suggest")

        if action.affects_commitment or "commitment" in operation or "commitment" in capability:
            return self._approval("approval_required_external_commitment")
        if operation in _PAYMENT_OPERATIONS or "payment" in capability:
            return self._approval("approval_required_payment")
        if operation in _MESSAGE_OPERATIONS or any(
            marker in capability for marker in ("message", "email", "sms")
        ):
            return self._approval("approval_required_external_message")
        if operation in _DELETE_OPERATIONS or any(
            marker in capability for marker in (".delete", ".remove", ".destroy")
        ):
            return self._approval("approval_required_irreversible")
        if not action.reversible:
            return self._approval("approval_required_irreversible")
        if action.external_effect:
            return self._approval("approval_required_external_effect")
        if (
            operation in self.approval_required_for
            or capability in self.approval_required_for
        ):
            return self._approval("approval_required_configured_action")
        if action.authority is ActionAuthority.APPROVAL_REQUIRED:
            return self._approval("approval_required_by_action")

        if action.risk == "high":
            return self._approval("approval_required_high_risk")

        if action.risk not in _KNOWN_RISK_LEVELS:
            return self._suggest("unknown_action_suggest")

        if action.authority is ActionAuthority.OBSERVE:
            return self._decision(
                True,
                False,
                "read_only_allowed",
                "The permitted action is read-only and requires no approval.",
                ActionAuthority.OBSERVE,
            )
        if action.authority is ActionAuthority.SUGGEST:
            return self._suggest("unknown_action_suggest")
        if action.authority is not ActionAuthority.AUTONOMOUS:
            return self._suggest("unknown_action_suggest")
        if agent_autonomy_level < 2:
            return self._suggest("agent_autonomy_insufficient")

        return self._decision(
            True,
            False,
            "reversible_internal_autonomous",
            "The action is permitted, internal, and recoverable.",
            ActionAuthority.AUTONOMOUS,
        )

    @staticmethod
    def _approval(reason_code: str) -> PolicyDecision:
        return ActionPolicy._decision(
            False,
            True,
            reason_code,
            "Human approval is required before this action can execute.",
            ActionAuthority.APPROVAL_REQUIRED,
        )

    @staticmethod
    def _suggest(reason_code: str) -> PolicyDecision:
        return ActionPolicy._decision(
            False,
            False,
            reason_code,
            "The action cannot be safely authorized; keep it as a suggestion.",
            ActionAuthority.SUGGEST,
        )

    @staticmethod
    def _decision(
        allowed: bool,
        approval_required: bool,
        reason_code: str,
        explanation: str,
        effective_authority: ActionAuthority,
    ) -> PolicyDecision:
        return PolicyDecision(
            allowed=allowed,
            approval_required=approval_required,
            reason_code=reason_code,
            explanation=explanation,
            effective_authority=effective_authority,
        )
