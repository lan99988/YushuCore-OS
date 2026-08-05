from __future__ import annotations

from dataclasses import dataclass

from runtime_core.models import AgentDefinition


class PermissionDenied(RuntimeError):
    pass


class AgentLifecycleError(RuntimeError):
    pass


class PermissionManager:
    def require(self, agent: AgentDefinition, permission: str) -> None:
        if permission not in set(agent.permissions):
            raise PermissionDenied(f"{permission}_denied")


@dataclass(frozen=True)
class PermissionDecision:
    capability: str
    status: str
    reason: str


class AgentPermissionMatrix:
    """Maps the Phase 4 capability matrix to explicit allow/request/deny results."""

    def check(self, agent: AgentDefinition, capability: str) -> PermissionDecision:
        if capability == "knowledge":
            return PermissionDecision(
                capability,
                "allowed" if "read_knowledge" in agent.permissions else "denied",
                "knowledge context is available through Gateway",
            )
        if capability == "cognition":
            return PermissionDecision(
                capability,
                "request" if "read_knowledge" in agent.permissions else "denied",
                "analysis is available, but higher-risk cognition remains reviewable",
            )
        if capability == "execute":
            if "execute" not in agent.permissions:
                status = "denied"
            elif agent.autonomy_level >= 3:
                status = "allowed"
            else:
                status = "request"
            return PermissionDecision(
                capability,
                status,
                "execution is bounded by autonomy level and Runtime policy",
            )
        if capability == "modify":
            return PermissionDecision(
                capability,
                "request" if "propose_change" in agent.permissions else "denied",
                "modification must enter Proposal / Approval",
            )
        raise ValueError(f"unknown capability: {capability}")
