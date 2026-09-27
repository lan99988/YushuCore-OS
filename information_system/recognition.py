"""多维识别引擎 —— 产出规格 §14 的「判别报告」。

设计立场（重要，勿淡化）：
- 本引擎是**确定性规则引擎**（`rule_based_v1`），不是大模型。所有判断可复现、可审计、离线可跑。
  接入 LLM 后端时通过 `backend` 注入，但**默认不联网**（`config/network.yaml` 默认 OFF）。
- **治理不变量：本引擎永远不会输出 `knowledge` 或 `core_knowledge`。**
  知识等级最多产出 `knowledge_candidate`，晋升为 `knowledge` 必须由人工确认
  （见 ADR-008 决策 5 与 `InformationObject.json` invariants）。
- 认知 OS 等级同理：只产出 `*_candidate`。
- 每一处非零置信度都必须能指回正文片段（evidence）或给出理由（reason）。

无模型时 **不臆造**：宁可标 `unknown_topic` 进观察区，也不强行归类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Iterable, Protocol

from .models import (
    DomainCandidate,
    InformationObject,
    RecognitionReport,
    Relation,
    ScoredItem,
)
from .projects import ProjectResolver
from .timeparse import resolve_time

BACKEND_RULE_BASED = "rule_based_v1"

# 领域关键词表。**这只是一份「已知领域的识别提示」，不是领域定义的来源**——
# 领域合法取值一律来自 DomainRegistry（见 DomainRegistry.json invariants）。
DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "工作": ("工作", "项目", "需求", "上线", "排期", "汇报", "客户", "会议", "绩效", "交付", "协作"),
    "学习": ("学习", "考试", "考研", "复习", "知识点", "教材", "真题", "课程", "背诵", "刷题", "笔记法"),
    "生活": ("生活", "家庭", "做饭", "购物", "旅行", "睡眠", "运动", "打扫", "作息", "花销", "家务"),
    "阅读": ("阅读", "读书", "书评", "摘录", "章节", "作者", "译本", "原书", "翻阅", "书单"),
    "AI": ("AI", "人工智能", "模型", "Agent", "智能体", "提示词", "大模型", "LLM", "推理", "上下文", "微调"),
}

TEMPORAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("instant", ("立即", "马上", "立刻", "现在就", "赶紧")),
    ("today", ("今天", "今日", "今晚", "本日")),
    (
        "short_term",
        (
            "本周", "这周", "这两周", "下周", "下下周", "周末", "下周末",
            "明天", "明日", "后天", "大后天", "这几天", "尽快", "短期",
            "本月", "下月", "下个月", "近期",
        ),
    ),
    (
        "long_term",
        ("长期", "持续", "以后", "未来", "常年", "长期积累", "长期主义", "明年", "年底"),
    ),
)

TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("task", ("待办", "任务", "要做", "安排", "完成", "截止")),
    ("principle", ("原则", "准则", "铁律", "永远是", "绝不可以", "底线", "红线")),
    ("model", ("模型", "框架", "范式", "公式", "架构", "机制", "网络")),
    ("method", ("方法", "步骤", "流程", "做法", "技巧", "SOP", "模板", "套路", "清单")),
    ("decision", ("决定", "决策", "选定", "敲定")),
    ("experience", ("经验", "复盘", "教训", "踩坑", "上次", "实践下来")),
    ("question", ("？", "?", "为什么", "如何", "怎么", "是否", "能不能")),
    ("idea", ("灵感", "点子", "想法", "不妨", "假设")),
    ("opinion", ("我认为", "观点", "看法", "可能", "或许")),
    ("fact", ("数据显示", "据统计", "事实", "经查", "实测")),
    ("event", ("会议", "活动", "发生", "日程")),
)

COGNITIVE_OS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("architecture_candidate", ("架构", "系统设计", "顶层设计", "基础设施")),
    ("os_rule_candidate", ("规则", "制度", "标准做法", "流程化", "以后一律", "从此")),
    ("principle_candidate", ("原则", "准则", "铁律", "永远", "绝不可以")),
    ("model_candidate", ("模型", "框架", "范式")),
    ("method_candidate", ("方法", "步骤", "流程", "SOP", "做法")),
    ("insight", ("启发", "意识到", "发现", "恍然大悟", "原来是")),
)

# 规范性（"以后应该怎么做"）句式模式。只补句式，不补裸词 —— 裸 `以后` 会把
# 「以后每天写周报」这类普通任务句误判为认知 OS 候选（见修复方案 P1-2 的风险条款）。
NORMATIVE_OS_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "os_rule_candidate",
        (
            re.compile(r"(以后|今后|从此)[^。！？!?\n；;]{0,20}(一律|都|必须|统一)"),
            re.compile(r"凡是[^。！？!?\n；;]{0,20}都"),
            re.compile(r"都应该|都不应该"),
        ),
    ),
    ("method_candidate", (re.compile(r"标准做法|流程化|制度化"),)),
)

ACTION_MARKERS = ("需要", "应当", "应该", "下一步", "记得", "要记得", "待", "建议")

# 强情态词：命中即认定为显式意图，可越过「能力陈述闸门」。
# `建议` 不算强词 —— "给出预算建议" 里它是名词，不是待办。
STRONG_ACTION_MARKERS = frozenset({"需要", "应当", "应该", "下一步", "记得", "要记得", "待"})

# 祈使句/动词型行动线索（P1-7）。命中后仍须通过"无过去式标记"闸门，
# 否则「我今天整理了桌面」会被误判为待办。
ACTION_VERB_PATTERN = re.compile(
    r"(发送|提交|联系|跟进|预约|回复|报名|缴费|报销|上传|取件|存档|备份|归档|"
    r"检查|整理|准备|撰写|起草|安排|提醒|发给|汇报|迁移|对接|申领|办理)"
)

PAST_TENSE_PATTERN = re.compile(r"(已经|已|了|过|完成过|昨天|前天|上次|之前)")

# 能力陈述闸门（仅用于动词回退路径）：`可以/能够/用来` 描述的是能力，不是待办。
CAPABILITY_PATTERN = re.compile(r"(可以|能够|能|用于|用来|有助于|支持)")

# 描述/定义句式排除（P1-3）：`是一种…架构` 这类是在**陈述既有事实**，不是在
# 主张"我以后应该怎么做"。若某次命中落在描述性前缀内，该次命中不计入 OS 判定。
DESCRIPTIVE_PREFIX_PATTERN = re.compile(
    r"(是一种|是一个|是一类|属于|指的是|定义为|叫做|称为|的一种|是指|本质上是)"
)

_CLAUSE_SPLIT = re.compile(r"[。！？!?；;\n：:]+")

KNOWLEDGE_MARKER_TYPES = frozenset({"method", "model", "principle", "experience", "decision"})

_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#\-\.]{2,}|[\u4e00-\u9fff]{2,}")
_CONCEPT_PATTERNS = (
    re.compile(r"《([^》]{2,40})》"),
    re.compile(r"「([^」]{2,40})」"),
    re.compile(r"\b([A-Z][A-Za-z0-9\-]{2,}(?:\s+[A-Z][A-Za-z0-9\-]{1,})?)\b"),
)
_SENTENCE_SPLIT = re.compile(r"[。！？!?\n；;]+")

DEFAULT_DOMAIN_THRESHOLD = 0.45


class RecognitionBackend(Protocol):
    name: str

    def analyze(
        self, *, object_id: str, title: str, text: str, known_domains: tuple[str, ...]
    ) -> dict[str, object]:
        ...


@dataclass
class RuleBasedBackend:
    """确定性规则后端。同一输入永远产出同一报告。"""

    name: str = BACKEND_RULE_BASED
    domain_keywords: dict[str, tuple[str, ...]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.domain_keywords is None:
            self.domain_keywords = dict(DOMAIN_KEYWORDS)

    # -------------------------------------------------------------- 工具

    @staticmethod
    def _first_hit(haystack: str, markers: Iterable[str]) -> str:
        for marker in markers:
            if marker in haystack:
                return marker
        return ""

    @staticmethod
    def _first_operative_hit(haystack: str, markers: Iterable[str]) -> str:
        """首个**非描述性**命中。描述性出现（`是一种…架构`）不算主张，跳过。"""
        clauses = _CLAUSE_SPLIT.split(haystack)
        for marker in markers:
            for clause in clauses:
                index = clause.find(marker)
                if index < 0:
                    continue
                prefix = clause[max(0, index - 40) : index]
                if DESCRIPTIVE_PREFIX_PATTERN.search(prefix):
                    continue
                return marker
        return ""

    @staticmethod
    def _normative_hit(haystack: str) -> tuple[str, str]:
        """规范性句式命中 → (等级, 命中片段)。命中失败返回 `("", "")`。"""
        clauses = _CLAUSE_SPLIT.split(haystack)
        for level, patterns in NORMATIVE_OS_PATTERNS:
            for pattern in patterns:
                for clause in clauses:
                    if pattern.search(clause):
                        return level, clause.strip()
        return "", ""

    @staticmethod
    def _snippet(text: str, marker: str, *, width: int = 40) -> str:
        index = text.find(marker)
        if index < 0:
            return ""
        start = max(0, index - width // 2)
        return text[start : start + width].replace("\n", " ").strip()

    def _concepts(self, text: str) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for pattern in _CONCEPT_PATTERNS:
            for match in pattern.findall(text):
                term = match.strip()
                if len(term) < 2 or term in seen:
                    continue
                seen.add(term)
                found.append((term, self._snippet(text, term)))
        return found[:8]

    def _domains(self, haystack: str, known_domains: tuple[str, ...]) -> list[tuple[str, float, str]]:
        scored: list[tuple[str, float, str]] = []
        for name in known_domains:
            markers = tuple(self.domain_keywords.get(name, ())) + (name,)
            hits = [marker for marker in markers if marker and marker in haystack]
            if not hits:
                continue
            # 命中的不同标记越多越可信；上限 0.95，避免出现「确定性满分」
            confidence = min(0.95, 0.35 + 0.15 * len(hits))
            scored.append((name, confidence, hits[0]))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored

    # -------------------------------------------------------------- 主逻辑

    def analyze(
        self, *, object_id: str, title: str, text: str, known_domains: tuple[str, ...]
    ) -> dict[str, object]:
        haystack = f"{title}\n{text}"
        folded = haystack.casefold()
        tokens = tuple(dict.fromkeys(_WORD_PATTERN.findall(haystack)))

        # 时间属性
        temporal_value = "no_requirement"
        temporal_marker = ""
        for value, markers in TEMPORAL_RULES:
            marker = self._first_hit(haystack, markers)
            if marker:
                temporal_value, temporal_marker = value, marker
                break

        # 类型（多值）
        types: list[str] = []
        type_evidence: dict[str, str] = {}
        for value, markers in TYPE_RULES:
            marker = self._first_hit(haystack, markers)
            if marker:
                types.append(value)
                type_evidence[value] = self._snippet(haystack, marker)

        # 知识等级：**封顶 knowledge_candidate**，绝不产出 knowledge / core_knowledge
        knowledge_marker = ""
        knowledge_level = "information"
        if set(types) & KNOWLEDGE_MARKER_TYPES:
            knowledge_level = "knowledge_candidate"
            for value in sorted(set(types) & KNOWLEDGE_MARKER_TYPES):
                knowledge_marker = type_evidence.get(value, "")
                break
        elif len(text) >= 200 and any(word in haystack for word in ("结论", "提炼", "总结", "要点")):
            knowledge_level = "knowledge_candidate"
            knowledge_marker = "结论/提炼/总结"

        # 认知 OS：先查关键词（排除描述性出现），再查规范性句式
        cognitive_level = "none"
        cognitive_marker = ""
        for value, markers in COGNITIVE_OS_RULES:
            marker = self._first_operative_hit(haystack, markers)
            if marker:
                cognitive_level, cognitive_marker = value, marker
                break
        if cognitive_level == "none":
            normative_level, normative_snippet = self._normative_hit(haystack)
            if normative_level:
                cognitive_level, cognitive_marker = normative_level, normative_snippet
        cognitive_detected = cognitive_level != "none"

        # 领域
        domain_scores = self._domains(haystack, known_domains)
        domains = tuple(
            DomainCandidate(
                name=name,
                confidence=confidence,
                evidence=(self._snippet(haystack, hit),),
                reason=f"命中领域标记「{hit}」",
            )
            for name, confidence, hit in domain_scores
        )
        top_domain = domains[0] if domains else None
        unknown_topic = top_domain is None or top_domain.confidence < DEFAULT_DOMAIN_THRESHOLD

        # 概念（只算一次，两处复用）
        concept_pairs = self._concepts(haystack)
        concepts = tuple(
            ScoredItem(
                label=term,
                confidence=0.5,
                evidence=((snippet,) if snippet else ()),
                reason="正文出现的专名/术语",
            )
            for term, snippet in concept_pairs
        )

        # 关系：与命中领域建立 related_to
        relations: list[Relation] = []
        if top_domain is not None:
            relations.append(
                Relation(
                    relation_type="related_to",
                    target_label=top_domain.name,
                    confidence=top_domain.confidence,
                    evidence=top_domain.evidence,
                    reason=f"内容与领域「{top_domain.name}」高度相关",
                )
            )

        # 行动建议（**只建议，不建任务**）
        # 闸门：①过去式（已发生的事不是待办）②能力陈述（可以/能够…不是待办，
        # 除非有强情态词）。两条闸门都只在没有强情态词时生效。
        actions: list[ScoredItem] = []
        seen_actions: set[str] = set()
        for sentence in _SENTENCE_SPLIT.split(text):
            stripped = sentence.strip()
            if not stripped or stripped in seen_actions:
                continue
            marker = self._first_hit(stripped, ACTION_MARKERS)
            if marker not in STRONG_ACTION_MARKERS:
                if CAPABILITY_PATTERN.search(stripped):
                    continue
            if not marker:
                verb = ACTION_VERB_PATTERN.search(stripped)
                if verb and not PAST_TENSE_PATTERN.search(stripped):
                    marker = verb.group(0)
            if marker and 4 <= len(stripped) <= 120:
                seen_actions.add(stripped)
                actions.append(
                    ScoredItem(
                        label=stripped,
                        confidence=0.6,
                        evidence=(stripped,),
                        reason=f"含行动性表述「{marker}」",
                    )
                )
            if len(actions) >= 3:
                break

        # 整体置信度：主信号加权
        parts: list[float] = []
        if temporal_marker:
            parts.append(0.7)
        if types:
            parts.append(min(0.9, 0.5 + 0.1 * len(types)))
        if top_domain is not None:
            parts.append(top_domain.confidence)
        overall = round(sum(parts) / len(parts), 4) if parts else 0.0

        evidence: list[str] = []
        reason_parts: list[str] = []
        if temporal_marker:
            evidence.append(self._snippet(haystack, temporal_marker))
            reason_parts.append(f"时间线索「{temporal_marker}」")
        if types:
            reason_parts.append("类型线索命中 " + "、".join(types))
        if top_domain is not None:
            reason_parts.append(f"领域线索指向「{top_domain.name}」")
        if unknown_topic:
            reason_parts.append("现有领域无法自然容纳，进入观察区")

        if unknown_topic:
            recommendation = "observe_unknown_topic"
        elif knowledge_level == "knowledge_candidate" or cognitive_detected:
            recommendation = "needs_human_review"
        elif actions:
            recommendation = "create_action_suggestion"
        else:
            recommendation = "process_normally"

        return {
            "backend": self.name,
            "temporal": {"value": temporal_value, "marker": temporal_marker},
            "types": types,
            "type_evidence": type_evidence,
            "knowledge_level": knowledge_level,
            "knowledge_marker": knowledge_marker,
            "cognitive_os": {
                "detected": cognitive_detected,
                "level": cognitive_level,
                "marker": cognitive_marker,
            },
            "domains": domain_scores,
            "unknown_topic": unknown_topic,
            "concepts": [(term, snippet) for term, snippet in concept_pairs],
            "relations": [],
            "actions": [item.label for item in actions],
            "recommendation": recommendation,
            "tokens": tokens,
            "evidence": evidence,
            "reason": "；".join(reason_parts),
            "confidence": overall,
            "_typed": {
                "concepts": concepts,
                "relations": relations,
                "actions": actions,
            },
        }


@dataclass
class RecognitionEngine:
    """把信息对象 + 正文转成 `RecognitionReport`。

    时间点解析（`deadline`）与项目匹配（`projects`）在**引擎层**完成，
    不扩展 backend 协议 —— 自定义后端（含测试替身）无需感知这两项能力。
    """

    backend: RecognitionBackend = None  # type: ignore[assignment]
    projects: ProjectResolver | None = None
    resolve_deadline: bool = True

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = RuleBasedBackend()
        if self.projects is None:
            self.projects = ProjectResolver.from_config()

    def _deadline(self, title: str, text: str, moment: datetime | None) -> tuple[str | None, dict]:
        if not self.resolve_deadline:
            return None, {}
        resolution = resolve_time(f"{title}\n{text}", now=moment)
        if resolution is None:
            return None, {}
        detail = resolution.to_dict()
        # 只有 point 才给 deadline；window / fuzzy 一律留空（不假装精确）
        deadline = resolution.deadline if resolution.kind == "point" and resolution.deadline else None
        return deadline, detail

    def recognize(
        self,
        obj: InformationObject,
        text: str,
        *,
        known_domains: tuple[str, ...] = (),
        object_id: str | None = None,
        moment: datetime | None = None,
    ) -> RecognitionReport:
        resolved_id = object_id or obj.resolved_object_id
        raw = self.backend.analyze(
            object_id=resolved_id,
            title=obj.title,
            text=text,
            known_domains=known_domains,
        )
        typed = raw.get("_typed") or {}
        concepts = tuple(typed.get("concepts") or ())
        relations = tuple(typed.get("relations") or ())
        actions = tuple(typed.get("actions") or ())

        deadline, temporal_detail = self._deadline(obj.title, text, moment)
        project_hits = () if self.projects is None else self.projects.resolve(title=obj.title, text=text)

        temporal_value = str((raw.get("temporal") or {}).get("value", "no_requirement"))
        temporal_marker = str((raw.get("temporal") or {}).get("marker", ""))
        temporal = ScoredItem(
            label=temporal_value,
            confidence=0.7 if temporal_marker else 0.0,
            evidence=((temporal_marker,) if temporal_marker else ()),
            reason=(f"时间线索「{temporal_marker}」" if temporal_marker else "未发现明确时间线索"),
        )

        cognitive = raw.get("cognitive_os") or {}
        knowledge_level = str(raw.get("knowledge_level", "information"))
        if knowledge_level not in {"information", "knowledge_candidate"}:
            # 治理兜底：后端越界时强制降级，绝不透传
            knowledge_level = "knowledge_candidate"

        return RecognitionReport(
            object_id=resolved_id,
            backend=str(raw.get("backend", self.backend.name)),
            temporal=temporal,
            types=tuple(raw.get("types") or ()),
            knowledge_level=knowledge_level,
            cognitive_os_detected=bool(cognitive.get("detected", False)),
            cognitive_os_level=str(cognitive.get("level", "none")),
            domains=tuple(
                DomainCandidate(
                    name=name,
                    confidence=confidence,
                    evidence=(hit,),
                    reason=f"命中领域标记「{hit}」",
                )
                for name, confidence, hit in (raw.get("domains") or ())
            ),
            concepts=concepts,
            relations=relations,
            projects=tuple(project_hits),
            actions=actions,
            new_domain_detected=bool(raw.get("unknown_topic", False)),
            observation_detected=bool(raw.get("unknown_topic", False)),
            recommendation_action=str(raw.get("recommendation", "process_normally")),
            confidence=float(raw.get("confidence", 0.0)),
            evidence=tuple(raw.get("evidence") or ()),
            reason=str(raw.get("reason", "")),
            deadline=deadline,
            temporal_detail=temporal_detail,
        )
