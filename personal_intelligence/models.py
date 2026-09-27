from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any


class SelfModelLayer(str, Enum):
    IDENTITY = "identity"
    VALUE = "value"
    PRINCIPLE = "principle"
    PREFERENCE = "preference"
    BEHAVIOR_PATTERN = "behavior_pattern"
    EXPERIENCE = "experience"


class PersonalRuleStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    REVOKED = "revoked"
    DEGRADED = "degraded"


class PersonalRuleTarget(str, Enum):
    TODAY = "today"
    ADJUST = "adjust"
    DECISION_GUIDANCE = "decision_guidance"


@dataclass(frozen=True)
class IdentityModel:
    roles: tuple[str, ...]
    life_stage: str
    important_domains: tuple[str, ...]
    self_description: str


@dataclass(frozen=True)
class ValueEntry:
    value: str
    priority: int
    description: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValueModel:
    values: tuple[ValueEntry, ...]


@dataclass(frozen=True)
class Goal:
    goal_type: str
    title: str
    priority: str
    status: str
    related_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoalModel:
    goals: tuple[Goal, ...]


@dataclass(frozen=True)
class Preference:
    category: str
    preference: str
    confidence: float
    source: str


@dataclass(frozen=True)
class PreferenceModel:
    preferences: tuple[Preference, ...]


@dataclass(frozen=True)
class ThinkingPattern:
    name: str
    usage: str
    frequency: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThinkingModel:
    patterns: tuple[ThinkingPattern, ...]


@dataclass(frozen=True)
class DecisionFactor:
    name: str
    weight: float


@dataclass(frozen=True)
class DecisionModel:
    decision_type: str
    factors: tuple[DecisionFactor, ...]
    risk: str


@dataclass(frozen=True)
class BehaviorPattern:
    pattern: str
    observation: str
    period: str
    confidence: float


@dataclass(frozen=True)
class BehaviorModel:
    patterns: tuple[BehaviorPattern, ...]


@dataclass(frozen=True)
class Capability:
    domain: str
    level: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityModel:
    capabilities: tuple[Capability, ...]


@dataclass(frozen=True)
class SelfModelSnapshot:
    identity: IdentityModel
    values: ValueModel
    goals: GoalModel
    preferences: PreferenceModel
    thinking: ThinkingModel
    decision: DecisionModel
    behavior: BehaviorModel
    capabilities: CapabilityModel
    version: int = 1

    @classmethod
    def empty(cls) -> "SelfModelSnapshot":
        return cls(
            identity=IdentityModel((), "", (), ""),
            values=ValueModel(()),
            goals=GoalModel(()),
            preferences=PreferenceModel(()),
            thinking=ThinkingModel(()),
            decision=DecisionModel("general", (), "low"),
            behavior=BehaviorModel(()),
            capabilities=CapabilityModel(()),
        )


_SENSITIVITIES = {"level_0", "level_1", "level_2", "level_3", "level_4"}


@dataclass(frozen=True)
class SelfModelNode:
    node_id: str
    layer: SelfModelLayer
    content: str
    source: str
    sensitivity: str = "level_2"
    status: str = "validated"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.content.strip() or not self.source.strip():
            raise ValueError("node_id, content, and source are required")
        if self.sensitivity not in _SENSITIVITIES:
            raise ValueError("invalid sensitivity")
        if self.version < 1:
            raise ValueError("version must be positive")


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    decision: str
    context: str
    options: tuple[str, ...]
    chosen_action: str
    reason: str
    evidence: tuple[str, ...] = ()
    outcome: str = ""
    reflection: str = ""
    agent_id: str = ""
    reviewer: str = ""
    correlation_id: str = ""
    created_at: str = ""
    rule_ids: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    rule_target: str = PersonalRuleTarget.DECISION_GUIDANCE.value

    def __post_init__(self) -> None:
        for name in ("decision_id", "decision", "context", "chosen_action", "reason"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        PersonalRuleTarget(self.rule_target)


@dataclass(frozen=True)
class PersonalRuleCandidate:
    rule_id: str
    hypothesis_id: str
    hypothesis: str
    suggested_action: str
    target: PersonalRuleTarget
    supporting_evidence: tuple[str, ...]
    counterexamples: tuple[str, ...]
    time_range: tuple[datetime, datetime]
    confidence: float
    scope: tuple[str, ...]
    status: PersonalRuleStatus = PersonalRuleStatus.CANDIDATE
    proposed_by: str = "personal_intelligence_engine"
    reviewer: str = ""
    review_note: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("rule_id", "hypothesis_id", "hypothesis", "suggested_action"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if not self.scope or any(not value.strip() for value in self.scope):
            raise ValueError("scope is required")
        if not self.supporting_evidence or len(self.time_range) != 2:
            raise ValueError("validated evidence and a time range are required")
        if any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None for value in self.time_range):
            raise ValueError("time_range values must be timezone-aware datetimes")
        object.__setattr__(self, "time_range", tuple(value.astimezone(timezone.utc) for value in self.time_range))
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "target", PersonalRuleTarget(self.target))
        object.__setattr__(self, "status", PersonalRuleStatus(self.status))


@dataclass(frozen=True)
class CognitiveProposal:
    proposal_id: str
    agent_id: str
    observation: str
    pattern: str
    question: str
    reason: str
    evidence: tuple[str, ...]
    confidence: float
    risk: str
    target_layer: SelfModelLayer
    status: str = "pending_human_review"
    approved: bool = False
    correlation_id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        for name in ("proposal_id", "agent_id", "observation", "pattern", "question", "reason"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.risk not in {"low", "medium", "high"}:
            raise ValueError("risk must be low, medium, or high")
        if self.approved and self.status != "approved":
            raise ValueError("approved proposal must have approved status")


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str = "personal-model-interface"
    model_version: str = "0.1"
    prompt_version: str = "0.1"
    policy_version: str = "0.1"
    provider: str = "local"
    local_only: bool = True
    max_sensitivity: str = "level_2"


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    reason: str
    max_sensitivity: str
