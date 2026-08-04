from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime_core.permissions import AgentLifecycleError


@dataclass(frozen=True)
class SchedulerRecord:
    agent_id: str
    status: str
    details: dict[str, Any]


class AgentScheduler:
    def __init__(self) -> None:
        self._states: dict[str, str] = {}

    def register(self, agent_id: str) -> None:
        if agent_id in self._states:
            raise ValueError(f"Agent already scheduled: {agent_id}")
        self._states[agent_id] = "registered"

    def activate(self, agent_id: str) -> None:
        self._require_known(agent_id)
        self._states[agent_id] = "active"

    def deactivate(self, agent_id: str) -> None:
        self._require_known(agent_id)
        self._states[agent_id] = "deactivated"

    def monitor(self, agent_id: str, details: dict[str, Any]) -> SchedulerRecord:
        self._require_known(agent_id)
        self._states[agent_id] = "monitored"
        return SchedulerRecord(agent_id=agent_id, status="monitored", details=dict(details))

    def update(self, agent_id: str, details: dict[str, Any]) -> SchedulerRecord:
        self._require_known(agent_id)
        self._states[agent_id] = "updated"
        return SchedulerRecord(agent_id=agent_id, status="updated", details=dict(details))

    def state(self, agent_id: str) -> str:
        self._require_known(agent_id)
        return self._states[agent_id]

    def require_active(self, agent_id: str) -> None:
        if self.state(agent_id) != "active":
            raise AgentLifecycleError("agent_not_active")

    def _require_known(self, agent_id: str) -> None:
        if agent_id not in self._states:
            raise AgentLifecycleError("agent_not_registered")
