"""Multi-object Cognitive Classification（计划书第二十一节）。

把一条信息层对象（InformationObject）显式映射为 0..n 个认知资产。
映射表见实施计划文档「认知对象映射」一节。

硬规则（与 ADR-008 一致）：
- 只产出候选级资产，confidence 沿用信息层；
- 未知主题不指派领域，标签可为空；
- 不在这里写任何外部系统（写外部走 CognitivePersistenceLayer，且须显式触发）。
"""

from __future__ import annotations

from typing import Any

from .models import BilingualTag, CognitiveAsset, Relation
from .tags import TagRegistry

# InformationObject.types → 认知类型
TYPE_TO_COGNITIVE: dict[str, str] = {
    "fact": "knowledge",
    "method": "knowledge",
    "model": "knowledge",
    "principle": "knowledge",
    "event": "knowledge",
    "task": "knowledge",
    "knowledge_candidate": "knowledge",
    "experience": "experience",
    "decision": "decision",
    "opinion": "belief",
    "idea": "note",
    "question": "note",
    # os_rule 属于系统规则，不进入认知资产层（属 Cognitive OS 治理，不在本次范围）
}


def _confidence_of(value: Any) -> float:
    if isinstance(value, float) and 0.0 <= value <= 1.0:
        return value
    return 0.0


def extract_cognitive_assets(obj: Any, *, tag_registry: TagRegistry | None = None) -> tuple[CognitiveAsset, ...]:
    """从 InformationObject 提取认知资产（多对象）。

    `obj` 鸭子类型：需要 title / types / concepts / relations / cognitive_os_level /
    cognitive_os_detected / confidence / object_id 属性（即 information_system.InformationObject）。
    """
    registry = tag_registry or TagRegistry()
    title = str(getattr(obj, "title", "")).strip()
    if not title:
        raise ValueError("InformationObject.title 不能为空")

    tags = registry.normalize(tuple(getattr(obj, "domains", ()) or ()))
    source_object_id = str(getattr(obj, "object_id", "") or getattr(obj, "resolved_object_id", ""))
    confidence = _confidence_of(getattr(obj, "confidence", 0.0))
    excerpt = str(getattr(obj, "excerpt", "")).strip()

    assets: list[CognitiveAsset] = []
    seen_types: set[str] = set()

    for info_type in getattr(obj, "types", ()) or ():
        cognitive_type = TYPE_TO_COGNITIVE.get(str(info_type))
        if cognitive_type is None or cognitive_type in seen_types:
            continue
        seen_types.add(cognitive_type)
        assets.append(
            CognitiveAsset(
                cognitive_type=cognitive_type,
                title=title,
                statement=excerpt,
                tags=tags,
                source_object_id=source_object_id,
                confidence=confidence,
            )
        )

    # Insight：cognitive_os 识别为 insight 时单列（不与 Knowledge 合并）
    cognitive_os_level = str(getattr(obj, "cognitive_os_level", "none"))
    if cognitive_os_level == "insight" and "insight" not in seen_types:
        assets.append(
            CognitiveAsset(
                cognitive_type="insight",
                title=title,
                statement=excerpt,
                tags=tags,
                source_object_id=source_object_id,
                confidence=confidence,
            )
        )

    # Concept：每个 concept 单独成资产（计划书第十六节：Tag 与 Concept 严格区分）
    for concept in getattr(obj, "concepts", ()) or ():
        label = str(getattr(concept, "label", "")).strip()
        if not label:
            continue
        concept_tags = registry.normalize((label,)) if not tags else tags
        assets.append(
            CognitiveAsset(
                cognitive_type="concept",
                title=label,
                statement=f"来自「{title}」的概念节点",
                tags=concept_tags,
                source_object_id=source_object_id,
                confidence=_confidence_of(getattr(concept, "confidence", 0.0)),
            )
        )

    # Relation：挂到首个资产上（目标 cognitive_id 尚未分配时留空由 PersistLayer 解析）
    if assets and getattr(obj, "relations", ()):
        relations = tuple(
            Relation(
                relation_type=str(getattr(relation, "relation_type", "")),
                target_cognitive_id=str(getattr(relation, "target_object_id", "") or getattr(relation, "target_label", "")),
                confidence=_confidence_of(getattr(relation, "confidence", 0.0)),
            )
            for relation in obj.relations
            if str(getattr(relation, "relation_type", "")).strip()
        )
        if relations:
            assets[0] = assets[0].with_updates(relations=relations)

    return tuple(assets)
