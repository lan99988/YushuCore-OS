from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
import math
import re
from typing import Any

from knowledge_system.gateway import GatewayNode


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AutonomyLevel(IntEnum):
    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


class ActionAuthority(str, Enum):
    OBSERVE = "observe"
    SUGGEST = "suggest"
    AUTONOMOUS = "autonomous"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    plugin_id: str
    capability: str
    authority: ActionAuthority
    reversible: bool
    external_effect: bool
    affects_commitment: bool
    risk: str
    payload_digest: str
    operation: str = ""
    resource: str = ""
    required_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("action_id", "plugin_id", "capability", "risk", "payload_digest"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
        if not _SHA256_PATTERN.fullmatch(self.payload_digest):
            raise ValueError("payload_digest must be a lowercase SHA-256 hex digest")
        if not isinstance(self.authority, ActionAuthority):
            raise ValueError("authority must be an ActionAuthority")
        for field_name in ("reversible", "external_effect", "affects_commitment"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be a boolean")
        for field_name in ("operation", "resource"):
            if not isinstance(getattr(self, field_name), str):
                raise ValueError(f"{field_name} must be a string")
        if not isinstance(self.required_permissions, tuple) or any(
            not isinstance(permission, str) or not permission.strip()
            for permission in self.required_permissions
        ):
            raise ValueError("required_permissions must be a tuple of non-empty strings")


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    approval_required: bool
    reason_code: str
    explanation: str
    effective_authority: ActionAuthority

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool or type(self.approval_required) is not bool:
            raise ValueError("allowed and approval_required must be booleans")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("explanation is required")
        if not isinstance(self.effective_authority, ActionAuthority):
            raise ValueError("effective_authority must be an ActionAuthority")


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
