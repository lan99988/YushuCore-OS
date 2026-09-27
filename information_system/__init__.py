"""信息层（Information Layer）。

上游入口层：任何来源的信息先成为一个 `InformationObject`，经识别后分流到各业务域。

对应 Schema：`04_数据中心（Data）/数据模型（Schema）/00_信息层（Information）/`
决策记录：`07_系统文档（Docs）/ADR/ADR-008_IMA_Information_Layer_Integration.md`

依赖方向（单向，不得反向）：
    information_system  →  （不依赖）02_执行引擎 / agents / knowledge_system

组件：
    models      数据模型与不变量
    store       SQLite 信息对象库（幂等 / 事件流 / 领域注册表）
    recognition 多维识别引擎（确定性规则，产出判别报告）
    observation 领域观察区（五层判定）与领域注册表状态机
    taxonomy    主题路径（领域祖先链 → 知识库文件夹路径；unknown 落「未分类」）
"""

from .models import (
    COGNITIVE_OS_CANDIDATE_LEVELS,
    COGNITIVE_OS_LEVELS,
    DECISION_STATES,
    DOMAIN_STATES,
    DOMAIN_TRANSITIONS,
    GOVERNED_DECISIONS,
    INFO_TYPES,
    KNOWLEDGE_LEVELS,
    LIFECYCLE_STATES,
    LIFECYCLE_TRANSITIONS,
    SOURCE_KINDS,
    TEMPORAL_VALUES,
    DomainCandidate,
    DomainRecord,
    InformationObject,
    LayerVerdict,
    RecognitionReport,
    Relation,
    ScoredItem,
    TopicObservation,
    compute_source_key,
    content_digest,
    make_domain_id,
    make_object_id,
    make_topic_id,
)
from .observation import (
    FIVE_LAYERS,
    LAYER_LABELS,
    LAYER_WEIGHTS,
    MIN_EVIDENCE_FOR_CANDIDATE,
    MIN_EVIDENCE_FOR_SUGGESTION,
    PROMOTE_THRESHOLD,
    DomainObservationService,
    ObservationEngine,
    propose_topic_label,
    week_key,
)
from .recognition import (
    BACKEND_RULE_BASED,
    DEFAULT_DOMAIN_THRESHOLD,
    DOMAIN_KEYWORDS,
    RecognitionEngine,
    RuleBasedBackend,
)
from .store import DEFAULT_DB_RELATIVE, SCHEMA_VERSION, InformationStore
from .taxonomy import (
    AUTOMATIC_DOMAIN_STATE,
    PATH_SEPARATOR,
    UNCLASSIFIED_SEGMENT,
    DomainIndex,
    ThemePathError,
    confirmed_domain_names,
    decide_segments,
    domain_chain,
    format_path,
    is_unclassified,
)

__all__ = [
    "AUTOMATIC_DOMAIN_STATE",
    "BACKEND_RULE_BASED",
    "COGNITIVE_OS_CANDIDATE_LEVELS",
    "COGNITIVE_OS_LEVELS",
    "DECISION_STATES",
    "DEFAULT_DB_RELATIVE",
    "DEFAULT_DOMAIN_THRESHOLD",
    "DOMAIN_KEYWORDS",
    "DOMAIN_STATES",
    "DOMAIN_TRANSITIONS",
    "DomainCandidate",
    "DomainIndex",
    "DomainObservationService",
    "DomainRecord",
    "FIVE_LAYERS",
    "GOVERNED_DECISIONS",
    "INFO_TYPES",
    "InformationObject",
    "InformationStore",
    "KNOWLEDGE_LEVELS",
    "LAYER_LABELS",
    "LAYER_WEIGHTS",
    "LIFECYCLE_STATES",
    "LIFECYCLE_TRANSITIONS",
    "LayerVerdict",
    "MIN_EVIDENCE_FOR_CANDIDATE",
    "MIN_EVIDENCE_FOR_SUGGESTION",
    "ObservationEngine",
    "PATH_SEPARATOR",
    "PROMOTE_THRESHOLD",
    "RecognitionEngine",
    "RecognitionReport",
    "Relation",
    "RuleBasedBackend",
    "SCHEMA_VERSION",
    "SOURCE_KINDS",
    "ScoredItem",
    "TEMPORAL_VALUES",
    "ThemePathError",
    "TopicObservation",
    "UNCLASSIFIED_SEGMENT",
    "compute_source_key",
    "confirmed_domain_names",
    "content_digest",
    "decide_segments",
    "domain_chain",
    "format_path",
    "is_unclassified",
    "make_domain_id",
    "make_object_id",
    "make_topic_id",
    "propose_topic_label",
    "week_key",
]
