from __future__ import annotations

from dataclasses import dataclass

from knowledge_system.gateway.models import AgentPolicy, GatewayNode


SENSITIVITY_RANK = {
    "level_0": 0,
    "level_1": 1,
    "level_2": 2,
    "level_3": 3,
    "level_4": 4,
}


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str


def check_read_permission(node: GatewayNode, agent_id: str, policy: AgentPolicy) -> PermissionDecision:
    in_allowed_folder = any(
        node.path == folder.rstrip("/") or node.path.startswith(folder.rstrip("/") + "/")
        for folder in policy.allowed_folders
    )
    if not in_allowed_folder:
        return PermissionDecision(False, "folder_denied")
    if not set(node.domain).intersection(policy.allowed_domains):
        return PermissionDecision(False, "domain_denied")
    allowed_agents = node.metadata.get("agent_access", [])
    if isinstance(allowed_agents, str):
        if allowed_agents not in SENSITIVITY_RANK:
            return PermissionDecision(False, "agent_denied")
    elif agent_id not in allowed_agents and "*" not in allowed_agents:
        return PermissionDecision(False, "agent_denied")
    if policy.allowed_types and node.type not in policy.allowed_types:
        return PermissionDecision(False, "type_denied")
    if node.status not in policy.readable_statuses:
        return PermissionDecision(False, "status_denied")
    if SENSITIVITY_RANK[node.sensitivity] > SENSITIVITY_RANK[policy.max_sensitivity]:
        return PermissionDecision(False, "sensitivity_requires_approval")
    return PermissionDecision(True, "approved")


def check_proposal_permission(node: GatewayNode, agent_id: str, policy: AgentPolicy) -> PermissionDecision:
    decision = check_read_permission(node, agent_id, policy)
    if decision.reason == "sensitivity_requires_approval":
        max_proposal_sensitivity = policy.max_proposal_sensitivity or policy.max_sensitivity
        if SENSITIVITY_RANK[node.sensitivity] > SENSITIVITY_RANK[max_proposal_sensitivity]:
            return PermissionDecision(False, "proposal_sensitivity_denied")
        return PermissionDecision(True, "proposal_only")
    return decision
