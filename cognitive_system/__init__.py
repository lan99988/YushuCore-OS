"""认知资产层（Cognitive Layer）。

双知识库认知系统（IMA + Feishu Dual Persistence），依据：
- `07_系统文档（Docs）/plans/2026-09-15-cognitive-dual-persistence-plan.md`
- `07_系统文档（Docs）/ADR/ADR-008_IMA_Information_Layer_Integration.md`

架构原则（计划书第四十九节）：
- 认知模型统一，存储实现解耦
- cognitive_id 为跨系统唯一主标识；IMA/飞书内部 ID 只作 *_ref
- 认知状态（active/superseded/...）与持久化状态（pending/synced/failed/conflict）严格分离

依赖方向：cognitive_system → information_system / integrations（单向）。
"""

from cognitive_system.models import (
    BilingualTag,
    CognitiveAsset,
    Relation,
    content_hash_of,
)
from cognitive_system.ids import CognitiveIdAllocator
from cognitive_system.store import CognitiveStore
from cognitive_system.tags import TagRegistry
from cognitive_system.mapping import extract_cognitive_assets
from cognitive_system.persistence import (
    CognitivePersistenceLayer,
    PersistOutcome,
    PersistencePolicy,
    WriteResult,
)
from cognitive_system.ima_writer import ImaCognitiveWriter
from cognitive_system.feishu_writer import FeishuCognitiveWriter
from cognitive_system.retrieval import CognitiveRetrieval, RetrievalHit

__all__ = [
    "BilingualTag",
    "CognitiveAsset",
    "CognitiveIdAllocator",
    "CognitivePersistenceLayer",
    "CognitiveRetrieval",
    "CognitiveStore",
    "FeishuCognitiveWriter",
    "ImaCognitiveWriter",
    "PersistOutcome",
    "PersistencePolicy",
    "RetrievalHit",
    "Relation",
    "TagRegistry",
    "WriteResult",
    "content_hash_of",
    "extract_cognitive_assets",
]
