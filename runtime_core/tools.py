from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime_core.models import AgentDefinition
from runtime_core.permissions import PermissionDenied, PermissionManager


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[..., Any]
    required_permission: str | None = None


class BoundToolManager:
    def __init__(self, manager: "ToolManager", agent: AgentDefinition) -> None:
        self._manager = manager
        self._agent = agent

    def call(self, name: str, **kwargs: Any) -> Any:
        return self._manager.call(self._agent, name, **kwargs)


class ToolManager:
    def __init__(self, permissions: PermissionManager, event_bus: Any | None = None) -> None:
        self._permissions = permissions
        self._event_bus = event_bus
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        required_permission: str | None = None,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        if not callable(handler):
            raise ValueError("tool handler must be callable")
        self._tools[name] = ToolSpec(
            name=name,
            handler=handler,
            required_permission=required_permission,
        )

    def bind(self, agent: AgentDefinition) -> BoundToolManager:
        return BoundToolManager(self, agent)

    def call(self, agent: AgentDefinition, name: str, **kwargs: Any) -> Any:
        try:
            spec = self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc
        if spec.required_permission:
            try:
                self._permissions.require(agent, spec.required_permission)
            except PermissionDenied as exc:
                if self._event_bus is not None:
                    self._event_bus.publish(
                        {
                            "event": "tool_denied",
                            "agent_id": agent.agent_id,
                            "tool": name,
                            "reason": str(exc),
                        }
                    )
                raise
        result = spec.handler(**kwargs)
        if self._event_bus is not None:
            self._event_bus.publish(
                {
                    "event": "tool_called",
                    "agent_id": agent.agent_id,
                    "tool": name,
                }
            )
        return result
