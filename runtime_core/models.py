from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
import math
from typing import Any

from knowledge_system.gateway import GatewayNode


class AutonomyLevel(IntEnum):
    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


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
class AgentRequest:
    task_id: str
    requester: str
    agent_id: str
    goal: str
    context: str
    constraints: tuple[str, ...] = ()
    permission: str = "requested"
    network_mode: str = "OFF"
    correlation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("task_id", "requester", "agent_id", "goal", "context"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")
        if self.permission not in {"requested", "approved"}:
            raise ValueError("permission must be requested or approved")
        if self.network_mode not in {"OFF", "ASSIST", "SYNC"}:
            raise ValueError("network_mode must be OFF, ASSIST, or SYNC")


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent_id: str
    result: str
    confidence: float
    sources: tuple[str, ...] = ()
    proposals: tuple[dict[str, Any], ...] = ()
    actions: tuple[str, ...] = ()
    reason: str = ""
    evidence: tuple[str, ...] = ()
    correlation_id: str = ""
    status: str = "draft"
    governance: AgentGovernance | None = None

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if not self.agent_id.strip():
            raise ValueError("agent_id is required")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.status.strip():
            raise ValueError("status is required")


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
    collaboration: Any = None
    correlation_id: str = ""


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
