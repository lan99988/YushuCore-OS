from __future__ import annotations

from runtime_core.models import AgentDefinition


class PermissionDenied(RuntimeError):
    pass


class PermissionManager:
    def require(self, agent: AgentDefinition, permission: str) -> None:
        if permission not in set(agent.permissions):
            raise PermissionDenied(f"{permission}_denied")
