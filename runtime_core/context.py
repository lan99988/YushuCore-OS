from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge_system.gateway import GatewayNode
from runtime_core.models import AgentDefinition
from runtime_core.permissions import PermissionManager


@dataclass(frozen=True)
class KnowledgeContext:
    knowledge: list[GatewayNode]
    experience: list[GatewayNode]
    principles: list[GatewayNode]


class ContextManager:
    def __init__(self, gateway_client: Any, permissions: PermissionManager) -> None:
        self._gateway_client = gateway_client
        self._permissions = permissions

    def build(self, agent: AgentDefinition, *, credential: str, task: str) -> KnowledgeContext:
        self._permissions.require(agent, "read_knowledge")
        response = self._gateway_client.get_context(
            task,
            agent_id=agent.agent_id,
            credential=credential,
        )
        return KnowledgeContext(
            knowledge=response.knowledge,
            experience=response.experience,
            principles=response.principles,
        )

    def build_with_access_grant(
        self,
        agent: AgentDefinition,
        *,
        credential: str,
        task: str,
        resource_path: str,
        max_sensitivity: str,
    ) -> KnowledgeContext:
        self._permissions.require(agent, "read_knowledge")
        response = self._gateway_client.get_context_with_access_grant(
            task,
            agent_id=agent.agent_id,
            credential=credential,
            resource_path=resource_path,
            max_sensitivity=max_sensitivity,
        )
        return KnowledgeContext(
            knowledge=response.knowledge,
            experience=response.experience,
            principles=response.principles,
        )
