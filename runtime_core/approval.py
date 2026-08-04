from __future__ import annotations

from typing import Any

from runtime_core.models import AgentDefinition
from runtime_core.permissions import PermissionManager


class ApprovalEngine:
    def __init__(self, gateway_client: Any, permissions: PermissionManager) -> None:
        self._gateway_client = gateway_client
        self._permissions = permissions

    def request_update(
        self,
        agent: AgentDefinition,
        *,
        credential: str,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
    ):
        self._permissions.require(agent, "propose_change")
        return self._gateway_client.request_update(
            agent_id=agent.agent_id,
            credential=credential,
            target_id=target_id,
            old=old,
            new=new,
            reason=reason,
            confidence=confidence,
            risk=risk,
        )

    def approve_change(self, proposal_id: str, *, reviewer: str, reviewer_credential: str):
        return self._gateway_client.approve_change(
            proposal_id,
            reviewer=reviewer,
            reviewer_credential=reviewer_credential,
        )
