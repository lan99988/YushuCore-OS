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
    def __init__(self, gateway: Any, permissions: PermissionManager) -> None:
        self._gateway = gateway
        self._permissions = permissions

    def build(self, agent: AgentDefinition, *, credential: str, task: str) -> KnowledgeContext:
        self._permissions.require(agent, "read_knowledge")
        response = self._gateway.get_context(
            task,
            agent_id=agent.agent_id,
            credential=credential,
        )
        return KnowledgeContext(
            knowledge=response.knowledge,
            experience=response.experience,
            principles=response.principles,
        )
