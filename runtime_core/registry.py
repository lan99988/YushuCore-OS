from __future__ import annotations

from runtime_core.models import AgentDefinition


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        if definition.agent_id in self._agents:
            raise ValueError(f"Agent already registered: {definition.agent_id}")
        self._agents[definition.agent_id] = definition

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent: {agent_id}") from exc

    def list(self) -> list[AgentDefinition]:
        return list(self._agents.values())
