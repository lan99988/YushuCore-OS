from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentPolicy:
    allowed_folders: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    max_sensitivity: str = "level_0"
    allowed_types: tuple[str, ...] = ()
    readable_statuses: tuple[str, ...] = ("validated", "permanent")


@dataclass(frozen=True)
class GatewayNode:
    id: str
    type: str
    title: str
    domain: tuple[str, ...]
    status: str
    confidence: float
    sensitivity: str
    path: str
    body: str
    metadata: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class QueryResponse:
    nodes: list[GatewayNode]
    permission: str
    denied_count: int
    invalid_count: int


@dataclass(frozen=True)
class ContextResponse:
    knowledge: list[GatewayNode]
    experience: list[GatewayNode]
    principles: list[GatewayNode]


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    agent: str
    target_id: str
    target_path: str
    target_digest: str
    old: str
    new: str
    reason: str
    confidence: float
    risk: str
    status: str
    requires_core_approval: bool
    created: str
    reviewer: str | None = None
    review_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Proposal":
        return cls(**value)
