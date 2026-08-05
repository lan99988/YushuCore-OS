from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from knowledge_system.gateway import GatewayNode


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model_name: str
    reason: str


@dataclass(frozen=True)
class AgentGovernance:
    agent_id: str
    permissions: tuple[str, ...]
    can_access: tuple[str, ...]
    cannot_access: tuple[str, ...]
    tools_called: tuple[str, ...]
    audit_recorded: bool


@dataclass(frozen=True)
class MemoryEntry:
    agent_id: str
    task: str
    output: Any
    created: str
    scope: str = "agent"


@dataclass(frozen=True)
class RuntimeResult:
    agent_id: str
    task: str
    output: Any
    model: ModelRoute


@dataclass(frozen=True)
class RuntimeContext:
    agent_id: str
    task: str
    model: ModelRoute
    knowledge: list[GatewayNode]
    experience: list[GatewayNode]
    principles: list[GatewayNode]
    memory: Any
    tools: Any
    approvals: Any


AgentHandler = Callable[[RuntimeContext], Any]


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    name: str
    domain: str
    autonomy_level: int
    risk_level: str
    permissions: tuple[str, ...]
    handler: AgentHandler
    description: str = ""
    model_policy: str = "local_first"

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id is required")
        if not self.name.strip():
            raise ValueError("name is required")
        if not self.domain.strip():
            raise ValueError("domain is required")
        if not 0 <= self.autonomy_level <= 4:
            raise ValueError("autonomy_level must be between 0 and 4")
        if self.risk_level not in {"low", "medium", "high"}:
            raise ValueError("risk_level must be low, medium, or high")
        if not callable(self.handler):
            raise ValueError("handler must be callable")
