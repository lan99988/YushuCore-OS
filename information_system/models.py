"""信息层数据模型。

对应 Schema：`04_数据中心（Data）/数据模型（Schema）/00_信息层（Information）/`

设计约束（见 ADR-008 与 InformationObject.json 的 invariants）：
- types 为多值，不得退化为单值枚举
- domains 合法取值来自 DomainRegistry，本模块不硬编码领域列表
- cognitive_os_level 只允许 candidate 级取值
- confidence 非 0 时必须同时具备 evidence 或 reason
- 正文不落本层，只落摘要与指纹
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import math
from typing import Any, Union


SOURCE_KINDS = frozenset(
    {
        "ima",
        "feishu",
        "web",
        "wechat",
        "pdf",
        "file",
        "image",
        "video",
        "audio",
        "ai_chat",
        "meeting",
        "manual",
    }
)

TEMPORAL_VALUES = frozenset({"instant", "today", "short_term", "long_term", "no_requirement"})

INFO_TYPES = frozenset(
    {
        "fact",
        "opinion",
        "idea",
        "question",
        "experience",
        "decision",
        "method",
        "model",
        "principle",
        "event",
        "task",
        "knowledge_candidate",
        "os_rule",
    }
)

KNOWLEDGE_LEVELS = ("information", "knowledge_candidate", "knowledge", "core_knowledge")

# 只允许候选级：AI 可以大胆理解，但不能大胆修改用户的认知系统
COGNITIVE_OS_LEVELS = (
    "none",
    "plain",
    "insight",
    "method_candidate",
    "model_candidate",
    "principle_candidate",
    "os_rule_candidate",
    "architecture_candidate",
)
COGNITIVE_OS_CANDIDATE_LEVELS = frozenset(level for level in COGNITIVE_OS_LEVELS if level.endswith("_candidate"))

LIFECYCLE_STATES = ("captured", "inbox", "processing", "useful", "knowledge", "archived")

DECISION_STATES = ("detected", "suggested", "confirmed", "rejected")

DOMAIN_STATES = ("observation", "candidate", "confirmed", "rejected", "merged", "archived")

# 必须经人工确认才能落为正式的类别（ADR-008 决策 5）
GOVERNED_DECISIONS = frozenset({"knowledge", "cognitive_os", "new_domain", "system_rule"})

LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "captured": frozenset({"inbox", "archived"}),
    "inbox": frozenset({"processing", "archived"}),
    "processing": frozenset({"useful", "inbox", "archived"}),
    "useful": frozenset({"knowledge", "archived"}),
    "knowledge": frozenset({"archived"}),
    "archived": frozenset({"inbox"}),
}

# 领域状态机：Observation → Candidate → Confirmed / Rejected / Merged
DOMAIN_TRANSITIONS: dict[str, frozenset[str]] = {
    "observation": frozenset({"candidate", "rejected", "merged", "archived"}),
    "candidate": frozenset({"confirmed", "rejected", "merged", "observation", "archived"}),
    "confirmed": frozenset({"merged", "archived"}),
    "rejected": frozenset({"observation"}),
    "merged": frozenset(),
    "archived": frozenset({"observation"}),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _check_confidence(value: float, *, label: str = "confidence") -> None:
    _require(math.isfinite(value), f"{label} must be finite")
    _require(0.0 <= value <= 1.0, f"{label} must be between 0 and 1")


def _check_provenance(value: float, evidence: tuple[str, ...], reason: str, *, label: str) -> None:
    """confidence 非 0 时必须可解释：不允许只有无法追溯的裸分数。"""
    if value > 0.0:
        _require(
            any(item.strip() for item in evidence) or reason.strip(),
            f"{label} with non-zero confidence requires evidence or reason",
        )


def compute_source_key(source: str, source_ref: str, content_digest: str = "") -> str:
    """来源幂等键。优先使用来源侧稳定 ID；缺失时回退到正文指纹。"""
    anchor = source_ref.strip() or content_digest.strip()
    _require(bool(anchor), "source_key requires a source_ref or content_digest")
    return hashlib.sha256(f"{source}::{anchor}".encode("utf-8")).hexdigest()


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_object_id(source_key: str) -> str:
    return f"INFO-{source_key[:24]}"


def make_domain_id(name: str) -> str:
    return f"DOM-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}"


def make_topic_id(label: str) -> str:
    return f"TOP-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class ScoredItem:
    """带置信度与出处的最小单元（概念 / 项目 / 行动建议共用）。"""

    label: str
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(bool(self.label.strip()), "label is required")
        _check_confidence(self.confidence, label=f"{self.label}.confidence")
        _check_provenance(self.confidence, self.evidence, self.reason, label=f"{self.label}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class DomainCandidate:
    name: str
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        _require(bool(self.name.strip()), "domain candidate name is required")
        _check_confidence(self.confidence, label=f"domain[{self.name}].confidence")
        _check_provenance(self.confidence, self.evidence, self.reason, label=f"domain[{self.name}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Relation:
    relation_type: str
    target_label: str
    target_object_id: str = ""
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        _require(bool(self.relation_type.strip()), "relation_type is required")
        _require(bool(self.target_label.strip()), "relation target_label is required")
        _check_confidence(self.confidence, label=f"relation[{self.relation_type}].confidence")
        _check_provenance(
            self.confidence, self.evidence, self.reason, label=f"relation[{self.relation_type}]"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_type": self.relation_type,
            "target_label": self.target_label,
            "target_object_id": self.target_object_id,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LayerVerdict:
    """新领域五层判定中的一层。对应规格 §10。"""

    layer: str
    score: float
    reason: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(bool(self.layer.strip()), "layer is required")
        _check_confidence(self.score, label=f"layer[{self.layer}].score")
        _require(bool(self.reason.strip()), f"layer[{self.layer}] requires a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "score": self.score,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class InformationObject:
    """信息对象。正文不在此层，只持有投影与结构化属性。"""

    source: str
    title: str
    temporal: str = "no_requirement"
    source_ref: str = ""
    source_container: str = ""
    excerpt: str = ""
    content_digest: str = ""
    deadline: str | None = None
    types: tuple[str, ...] = ()
    knowledge_level: str = "information"
    cognitive_os_detected: bool = False
    cognitive_os_level: str = "none"
    domains: tuple[str, ...] = ()
    domain_candidates: tuple[DomainCandidate, ...] = ()
    unknown_topic: bool = False
    concepts: tuple[ScoredItem, ...] = ()
    relations: tuple[Relation, ...] = ()
    projects: tuple[ScoredItem, ...] = ()
    actions: tuple[ScoredItem, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""
    status: str = "captured"
    decision_state: str = "detected"
    reviewer: str = ""
    review_time: str | None = None
    correlation_id: str = ""
    object_id: str = ""

    def __post_init__(self) -> None:
        _require(self.source in SOURCE_KINDS, f"unsupported source: {self.source}")
        _require(bool(self.title.strip()), "title is required")
        _require(self.temporal in TEMPORAL_VALUES, f"invalid temporal: {self.temporal}")
        _require(self.knowledge_level in KNOWLEDGE_LEVELS, f"invalid knowledge_level: {self.knowledge_level}")
        _require(self.cognitive_os_level in COGNITIVE_OS_LEVELS, f"invalid cognitive_os_level: {self.cognitive_os_level}")
        _require(self.status in LIFECYCLE_STATES, f"invalid status: {self.status}")
        _require(self.decision_state in DECISION_STATES, f"invalid decision_state: {self.decision_state}")
        for value in self.types:
            _require(value in INFO_TYPES, f"invalid type: {value}")
        # 多值不变量：types 允许为空（捕获期尚未识别），但一旦非空即保持多值容器
        _require(len(set(self.domains)) == len(self.domains), "domains must not contain duplicates")
        _require(len(set(self.types)) == len(self.types), "types must not contain duplicates")
        if self.cognitive_os_detected:
            _require(self.cognitive_os_level != "none", "cognitive_os detected requires a level")
        # 治理不变量：未确认时不得携带正式认知等级（本字段本就只允许 candidate，此处再加一道）
        if self.decision_state != "confirmed":
            _require(
                self.cognitive_os_level in COGNITIVE_OS_CANDIDATE_LEVELS or self.cognitive_os_level in {"none", "plain", "insight"},
                "unconfirmed object may not carry a beyond-candidate cognitive level",
            )
        if self.decision_state == "confirmed":
            _require(bool(self.reviewer.strip()), "confirmed object requires a reviewer")
        _check_confidence(self.confidence)
        _check_provenance(self.confidence, self.evidence, self.reason, label="object")

    @property
    def source_key(self) -> str:
        return compute_source_key(self.source, self.source_ref, self.content_digest)

    @property
    def resolved_object_id(self) -> str:
        return self.object_id or make_object_id(self.source_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.resolved_object_id,
            "source_key": self.source_key,
            "source": self.source,
            "source_ref": self.source_ref,
            "source_container": self.source_container,
            "title": self.title,
            "excerpt": self.excerpt,
            "content_digest": self.content_digest,
            "temporal": self.temporal,
            "deadline": self.deadline,
            "types": list(self.types),
            "knowledge_level": self.knowledge_level,
            "cognitive_os_detected": self.cognitive_os_detected,
            "cognitive_os_level": self.cognitive_os_level,
            "domains": list(self.domains),
            "domain_candidates": [item.to_dict() for item in self.domain_candidates],
            "unknown_topic": self.unknown_topic,
            "concepts": [item.to_dict() for item in self.concepts],
            "relations": [item.to_dict() for item in self.relations],
            "projects": [item.to_dict() for item in self.projects],
            "actions": [item.to_dict() for item in self.actions],
            "attributes": dict(self.attributes),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "status": self.status,
            "decision_state": self.decision_state,
            "reviewer": self.reviewer,
            "review_time": self.review_time,
            "correlation_id": self.correlation_id,
        }

    def with_lifecycle(self, status: str) -> "InformationObject":
        if status == self.status:
            return self
        allowed = LIFECYCLE_TRANSITIONS.get(self.status, frozenset())
        _require(status in allowed, f"illegal lifecycle transition: {self.status} -> {status}")
        return replace(self, status=status)

    def confirmed(self, *, reviewer: str, review_time: str) -> "InformationObject":
        _require(bool(reviewer.strip()), "reviewer is required for confirmation")
        return replace(self, decision_state="confirmed", reviewer=reviewer, review_time=review_time)


@dataclass(frozen=True)
class RecognitionReport:
    """识别引擎的判别报告。对应规格 §14。"""

    object_id: str
    backend: str
    temporal: ScoredItem
    types: tuple[Union[str, ScoredItem], ...] = ()
    knowledge_level: str = "information"
    cognitive_os_detected: bool = False
    cognitive_os_level: str = "none"
    domains: tuple[DomainCandidate, ...] = ()
    concepts: tuple[ScoredItem, ...] = ()
    relations: tuple[Relation, ...] = ()
    projects: tuple[ScoredItem, ...] = ()
    actions: tuple[ScoredItem, ...] = ()
    new_domain_detected: bool = False
    observation_detected: bool = False
    recommendation_action: str = "process_normally"
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""
    # 时间点：仅有明确日期/时刻时才填（ISO 8601 带偏移）。窗口与模糊表述留空，
    # 细节放 `temporal_detail`，**不伪造精确 deadline**（见 timeparse 模块约定）。
    deadline: str | None = None
    temporal_detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(bool(self.object_id.strip()), "object_id is required")
        _require(bool(self.backend.strip()), "backend is required")
        _require(self.knowledge_level in KNOWLEDGE_LEVELS, f"invalid knowledge_level: {self.knowledge_level}")
        _require(self.cognitive_os_level in COGNITIVE_OS_LEVELS, f"invalid cognitive_os_level: {self.cognitive_os_level}")
        _require(bool(self.recommendation_action.strip()), "recommendation_action is required")
        _check_confidence(self.confidence)
        _check_provenance(self.confidence, self.evidence, self.reason, label="report")
        if self.cognitive_os_detected:
            _require(self.cognitive_os_level != "none", "cognitive_os detected requires a level")

    def to_dict(self) -> dict[str, Any]:
        return {
            "recognition": {
                "object_id": self.object_id,
                "backend": self.backend,
                "temporal": self.temporal.to_dict(),
                "types": [item if isinstance(item, str) else item.to_dict() for item in self.types],
                "knowledge_level": self.knowledge_level,
                "cognitive_os": {
                    "detected": self.cognitive_os_detected,
                    "level": self.cognitive_os_level,
                },
                "domains": [item.to_dict() for item in self.domains],
                "concepts": [item.to_dict() for item in self.concepts],
                "relations": [item.to_dict() for item in self.relations],
                "projects": [item.to_dict() for item in self.projects],
                "actions": [item.to_dict() for item in self.actions],
                "new_domain": {"detected": self.new_domain_detected},
                "observation": {"detected": self.observation_detected},
                "recommendation": {"action": self.recommendation_action},
                "confidence": self.confidence,
                "evidence": list(self.evidence),
                "reason": self.reason,
                "deadline": self.deadline,
                "temporal_detail": dict(self.temporal_detail),
            }
        }


@dataclass(frozen=True)
class DomainRecord:
    name: str
    state: str = "observation"
    slug: str = ""
    parent_id: str | None = None
    description: str = ""
    evidence_count: int = 0
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    reason: str = ""
    merged_into: str | None = None
    promoted_from: str | None = None
    confirmed_by: str = ""
    confirmed_at: str | None = None
    domain_id: str = ""

    def __post_init__(self) -> None:
        _require(bool(self.name.strip()), "domain name is required")
        _require(self.state in DOMAIN_STATES, f"invalid domain state: {self.state}")
        _check_confidence(self.confidence, label=f"domain[{self.name}].confidence")
        _check_provenance(self.confidence, self.evidence, self.reason, label=f"domain[{self.name}]")
        if self.state == "confirmed":
            _require(bool(self.confirmed_by.strip()), "confirmed domain requires confirmed_by")
        if self.state == "merged":
            _require(bool((self.merged_into or "").strip()), "merged domain requires merged_into")

    @property
    def resolved_domain_id(self) -> str:
        return self.domain_id or make_domain_id(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.resolved_domain_id,
            "name": self.name,
            "slug": self.slug,
            "parent_id": self.parent_id,
            "state": self.state,
            "description": self.description,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "merged_into": self.merged_into,
            "promoted_from": self.promoted_from,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }

    def transition(self, state: str, *, actor: str = "", at: str = "") -> "DomainRecord":
        allowed = DOMAIN_TRANSITIONS.get(self.state, frozenset())
        _require(state in allowed, f"illegal domain transition: {self.state} -> {state}")
        if state == "confirmed":
            _require(bool(actor.strip()), "confirming a domain requires an actor")
            return replace(self, state=state, confirmed_by=actor, confirmed_at=at or None)
        return replace(self, state=state)


@dataclass(frozen=True)
class TopicObservation:
    """未知主题观察记录。对应规格 §9/§11。"""

    label: str
    state: str = "observation"
    layers: tuple[LayerVerdict, ...] = ()
    object_ids: tuple[str, ...] = ()
    growth: dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""
    topic_id: str = ""

    def __post_init__(self) -> None:
        _require(bool(self.label.strip()), "topic label is required")
        _require(self.state in DOMAIN_STATES, f"invalid topic state: {self.state}")
        _check_confidence(self.confidence, label=f"topic[{self.label}].confidence")
        _check_provenance(self.confidence, (), self.reason, label=f"topic[{self.label}]")

    @property
    def resolved_topic_id(self) -> str:
        return self.topic_id or make_topic_id(self.label)

    @property
    def layer_scores(self) -> dict[str, float]:
        return {item.layer: item.score for item in self.layers}

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.resolved_topic_id,
            "label": self.label,
            "state": self.state,
            "layers": [item.to_dict() for item in self.layers],
            "object_ids": list(self.object_ids),
            "growth": dict(self.growth),
            "confidence": self.confidence,
            "reason": self.reason,
        }

    def transition(self, state: str) -> "TopicObservation":
        allowed = DOMAIN_TRANSITIONS.get(self.state, frozenset())
        _require(state in allowed, f"illegal topic transition: {self.state} -> {state}")
        return replace(self, state=state)
