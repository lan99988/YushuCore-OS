from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from runtime_core.models import AgentDefinition, RuntimeContext


AgentHandlerMap = dict[str, Callable[[RuntimeContext], Any]]


def load_agent_definitions(path: str | Path, handlers: AgentHandlerMap) -> list[AgentDefinition]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise ValueError("agent config must contain an agents list")

    definitions: list[AgentDefinition] = []
    for raw_agent in agents:
        if not isinstance(raw_agent, dict):
            raise ValueError("agent entries must be mappings")
        handler_id = raw_agent.get("handler")
        if not isinstance(handler_id, str) or not handler_id.strip():
            raise ValueError("agent handler is required")
        try:
            handler = handlers[handler_id]
        except KeyError as exc:
            raise ValueError(f"unknown agent handler: {handler_id}") from exc

        permissions = raw_agent.get("permissions", [])
        if not isinstance(permissions, list) or not all(
            isinstance(item, str) and item.strip() for item in permissions
        ):
            raise ValueError("agent permissions must be a list of non-empty strings")

        definitions.append(
            AgentDefinition(
                agent_id=str(raw_agent.get("agent_id", "")),
                name=str(raw_agent.get("name", "")),
                domain=str(raw_agent.get("domain", "")),
                autonomy_level=int(raw_agent.get("autonomy_level", -1)),
                risk_level=str(raw_agent.get("risk_level", "")),
                permissions=tuple(permissions),
                handler=handler,
                description=str(raw_agent.get("description", "")),
                model_policy=str(raw_agent.get("model_policy", "local_first")),
            )
        )
    return definitions
