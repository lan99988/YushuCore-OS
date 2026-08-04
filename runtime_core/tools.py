from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime_core.models import AgentDefinition
from runtime_core.permissions import PermissionManager


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
    def __init__(self, permissions: PermissionManager) -> None:
        self._permissions = permissions
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
            self._permissions.require(agent, spec.required_permission)
        return spec.handler(**kwargs)
