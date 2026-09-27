"""认知资产数据模型。

对应计划书第五节冻结的八类一级对象：
Source / Note / Experience / Knowledge / Concept / Insight / Belief / Decision。

设计约束：
- cognitive_id 是跨系统主标识；ima_ref / feishu_ref 只作引用（禁止 1/2/3 号禁令）
- 认知状态与持久化状态分离（计划书第十一节）
- 标签一律中英双语（用户要求）
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from typing import Any

# ---------------------------------------------------------------- 枚举与常量

COGNITIVE_TYPE_PREFIXES: dict[str, str] = {
    "source": "SRC",
    "note": "NOTE",
    "experience": "EXP",
    "knowledge": "KNW",
    "concept": "CON",
    "insight": "INS",
    "belief": "BEL",
    "decision": "DEC",
}

# 类型中英对照 —— 双语标签体系的一部分（文件夹命名、飞书「类型」字段共用）
COGNITIVE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "source": ("来源", "Source"),
    "note": ("笔记", "Note"),
    "experience": ("经验", "Experience"),
    "knowledge": ("知识", "Knowledge"),
    "concept": ("概念", "Concept"),
    "insight": ("洞察", "Insight"),
    "belief": ("信念", "Belief"),
    "decision": ("决策", "Decision"),
}

COGNITIVE_TYPES = tuple(COGNITIVE_TYPE_PREFIXES)

COGNITIVE_STATUSES = ("active", "revised", "superseded", "rejected", "archived")

PERSISTENCE_STATUSES = ("pending", "synced", "failed", "conflict")

# 跨库一致性状态（计划书第二十四节）
SYNC_STATES = (
    "PENDING",
    "SYNCED",
    "IMA_ONLY",
    "FEISHU_ONLY",
    "CONTENT_CONFLICT",
    "SYNC_FAILED",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class BilingualTag:
    """中英双语标签。zh 为规范键；en 缺失时 status=candidate（不阻断写入）。"""

    zh: str
    en: str = ""
    status: str = "confirmed"  # confirmed | candidate

    def __post_init__(self) -> None:
        _require(bool(self.zh.strip()), "标签中文（zh）不能为空")
        _require(self.status in ("confirmed", "candidate"), f"非法标签状态: {self.status}")
        if self.status == "confirmed":
            _require(bool(self.en.strip()), "confirmed 标签必须同时具备英文（en）")

    @property
    def is_candidate(self) -> bool:
        return self.status == "candidate"

    def to_dict(self) -> dict[str, str]:
        return {"zh": self.zh, "en": self.en, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BilingualTag":
        return cls(zh=str(data.get("zh", "")).strip(), en=str(data.get("en", "")).strip(), status=str(data.get("status", "confirmed")))


@dataclass(frozen=True)
class Relation:
    """认知资产间关系。target 用 cognitive_id（禁令 4/5：不得用 record_id / media_id）。"""

    relation_type: str
    target_cognitive_id: str
    confidence: float = 0.0

    def __post_init__(self) -> None:
        _require(bool(self.relation_type.strip()), "relation_type 不能为空")
        _require(bool(self.target_cognitive_id.strip()), "target_cognitive_id 不能为空")
        _require(0.0 <= self.confidence <= 1.0, "relation.confidence 必须在 0~1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_type": self.relation_type,
            "target_cognitive_id": self.target_cognitive_id,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relation":
        return cls(
            relation_type=str(data.get("relation_type", "")),
            target_cognitive_id=str(data.get("target_cognitive_id", "")),
            confidence=float(data.get("confidence", 0.0)),
        )


def content_hash_of(*, title: str, statement: str, tags: tuple[BilingualTag, ...], version: int) -> str:
    """内容指纹：标题 + 正文 + 规范化标签 + 版本。用于跨库一致性比对（计划书第二十五节）。"""
    canonical_tags = "|".join(f"{tag.zh}={tag.en}" for tag in sorted(tags, key=lambda t: t.zh))
    canonical = f"{title.strip()}||{statement.strip()}||{canonical_tags}||{version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CognitiveAsset:
    """认知资产。一条输入可产出多个（Multi-object Cognitive Classification）。"""

    cognitive_type: str
    title: str
    statement: str = ""
    tags: tuple[BilingualTag, ...] = ()
    source_object_id: str = ""  # 信息层 object_id 追溯锚点
    relations: tuple[Relation, ...] = ()
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    cognitive_status: str = "active"
    version: int = 1
    cognitive_id: str = ""
    ima_status: str = "pending"
    ima_ref: str = ""
    feishu_status: str = "pending"
    feishu_ref: str = ""
    sync_state: str = "PENDING"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        _require(self.cognitive_type in COGNITIVE_TYPES, f"非法认知类型: {self.cognitive_type}")
        _require(bool(self.title.strip()), "title 不能为空")
        _require(self.cognitive_status in COGNITIVE_STATUSES, f"非法认知状态: {self.cognitive_status}")
        _require(self.ima_status in PERSISTENCE_STATUSES, f"非法 IMA 持久化状态: {self.ima_status}")
        _require(self.feishu_status in PERSISTENCE_STATUSES, f"非法飞书持久化状态: {self.feishu_status}")
        _require(self.sync_state in SYNC_STATES, f"非法 sync_state: {self.sync_state}")
        _require(0.0 <= self.confidence <= 1.0, "confidence 必须在 0~1")
        _require(self.version >= 1, "version 必须 >= 1")
        _require(len(set(self.tags)) == len(self.tags), "tags 不得重复")
        if self.cognitive_id:
            expected_prefix = COGNITIVE_TYPE_PREFIXES[self.cognitive_type]
            _require(
                self.cognitive_id.startswith(f"{expected_prefix}-"),
                f"cognitive_id 前缀必须为 {expected_prefix}-: {self.cognitive_id}",
            )

    # ------------------------------------------------------------ 派生值

    @property
    def type_prefix(self) -> str:
        return COGNITIVE_TYPE_PREFIXES[self.cognitive_type]

    @property
    def type_label(self) -> tuple[str, str]:
        """(中文, 英文) 类型标签。"""
        return COGNITIVE_TYPE_LABELS[self.cognitive_type]

    @property
    def content_hash(self) -> str:
        return content_hash_of(title=self.title, statement=self.statement, tags=self.tags, version=self.version)

    @property
    def tag_zh(self) -> tuple[str, ...]:
        return tuple(tag.zh for tag in self.tags)

    @property
    def tag_en(self) -> tuple[str, ...]:
        return tuple(tag.en for tag in self.tags if tag.en)

    # ------------------------------------------------------------ 变更

    def with_updates(self, **changes: Any) -> "CognitiveAsset":
        return replace(self, **changes)

    def bump_version(self, *, title: str | None = None, statement: str | None = None, tags: tuple[BilingualTag, ...] | None = None) -> "CognitiveAsset":
        """内容变更：版本 +1，持久化状态回到 pending，由 Persistence Layer 重新派发。"""
        return replace(
            self,
            title=title if title is not None else self.title,
            statement=statement if statement is not None else self.statement,
            tags=tags if tags is not None else self.tags,
            version=self.version + 1,
            ima_status="pending",
            feishu_status="pending",
            sync_state="PENDING",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognitive_id": self.cognitive_id,
            "cognitive_type": self.cognitive_type,
            "type_label": {"zh": self.type_label[0], "en": self.type_label[1]},
            "title": self.title,
            "statement": self.statement,
            "tags": [tag.to_dict() for tag in self.tags],
            "tag_zh": list(self.tag_zh),
            "tag_en": list(self.tag_en),
            "source_object_id": self.source_object_id,
            "relations": [relation.to_dict() for relation in self.relations],
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "cognitive_status": self.cognitive_status,
            "version": self.version,
            "content_hash": self.content_hash,
            "ima_status": self.ima_status,
            "ima_ref": self.ima_ref,
            "feishu_status": self.feishu_status,
            "feishu_ref": self.feishu_ref,
            "sync_state": self.sync_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
