"""新领域观察区与领域注册表（规格 §9~§13、§27）。

职责边界：
- **观察区**（`topic_observation`）：现有领域无法自然容纳时，先落 `unknown` 进观察区，
  逐层记录判定依据，禁止强行归类（DomainRegistry invariant「错误分类比暂时没有分类更危险」）。
- **注册表**（`domain_registry`）：Observation → Candidate → Confirmed / Rejected / Merged。
  AI 可以大胆提出候选，**但 `confirmed` 必须人工执行**（ADR-008 决策 5）。

设计约束：
- 五层名与权重是本模块的确定性策略，不是模型输出；每层必须给出 `reason` 与 `evidence`。
- 新关键词 ≠ 新领域：单次出现只落 observation，累计证据达到阈值才允许升为 candidate。
- 本模块**永不**调用 `confirmed` 迁移；该方法只暴露给人工调用方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any, Protocol, Sequence

from .models import (
    DomainRecord,
    LayerVerdict,
    RecognitionReport,
    TopicObservation,
)

# 五层判定（对应规格 §10，层名与 DomainRegistry.json 的 layers 字段一致）
FIVE_LAYERS: tuple[str, ...] = (
    "semantic_distance",
    "new_concept_vs_combination",
    "explanation_cost",
    "independence",
    "growth_potential",
)

LAYER_LABELS: dict[str, str] = {
    "semantic_distance": "与现有领域的语义距离",
    "new_concept_vs_combination": "新概念 vs 已有概念组合",
    "explanation_cost": "用现有体系解释的成本",
    "independence": "能否独立成立",
    "growth_potential": "未来增长潜力",
}

# 聚合权重：语义距离与解释成本是最强信号
LAYER_WEIGHTS: dict[str, float] = {
    "semantic_distance": 0.28,
    "new_concept_vs_combination": 0.20,
    "explanation_cost": 0.22,
    "independence": 0.15,
    "growth_potential": 0.15,
}

PROMOTE_THRESHOLD = 0.60
MIN_EVIDENCE_FOR_CANDIDATE = 2
MIN_EVIDENCE_FOR_SUGGESTION = 3

# 合并建议阈值（P2）。只用于产出**建议**，任何合并都必须人工执行。
MERGE_SIMILARITY_THRESHOLD = 0.80
MERGE_CONTAINMENT_THRESHOLD = 0.60

_NAME_NORMALIZE = re.compile(r"[\s\u3000\-_/·．.]+")


def normalize_domain_name(name: str) -> str:
    """领域名规范化：去空格/连字符/点号并折叠大小写。用于发现字面重复。"""
    return _NAME_NORMALIZE.sub("", name.strip()).casefold()

# 初始领域清单的**唯一来源**是 Schema（`DomainRegistry.json` 的 `initial_domains`），
# 代码里不得内联这份清单（DomainRegistry invariant 第 1 条）。
SCHEMA_DIR = (
    Path(__file__).resolve().parents[1]
    / "04_数据中心（Data）"
    / "数据模型（Schema）"
    / "00_信息层（Information）"
)
DOMAIN_REGISTRY_SCHEMA = SCHEMA_DIR / "DomainRegistry.json"
SEED_ACTOR = "schema:initial_domains"

_LABEL_STRIP = re.compile(r"[\s\u3000，。！？、；：,.!?;:【】\[\]（）()《》「」\"'`~—\-_/\\|]+")
_CONCEPT_HEAD = re.compile(r"^[\u4e00-\u9fff]{2,}")


class StoreLike(Protocol):
    """只依赖本模块真正用到的那部分存储接口（便于测试注入）。"""

    def get_topic(self, label: str) -> dict[str, Any] | None: ...
    def list_topics(self, *, state: str | None = None) -> list[dict[str, Any]]: ...
    def upsert_topic(self, observation: TopicObservation) -> str: ...
    def transition_topic(self, label: str, state: str) -> str: ...
    def get_domain(self, name: str) -> dict[str, Any] | None: ...
    def list_domains(self, *, state: str | None = None) -> list[dict[str, Any]]: ...
    def upsert_domain(self, record: DomainRecord, *, actor: str = "system") -> str: ...
    def transition_domain(self, name: str, state: str, *, actor: str = "") -> str: ...


def week_key(moment: datetime | None = None) -> str:
    """ISO 周键，如 `2026-W38`。用于增长趋势分桶。"""
    stamp = moment or datetime.now(timezone.utc)
    iso = stamp.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def propose_topic_label(*, title: str, text: str, report: RecognitionReport) -> str:
    """为未知主题提出一个候选名。用户可改名，改名不丢证据（见 DomainRegistry）。"""
    for item in sorted(report.concepts, key=lambda c: (-c.confidence, -len(c.label))):
        head = _CONCEPT_HEAD.match(item.label.strip())
        if head:
            return head.group(0)[:16]
        if len(item.label.strip()) >= 2:
            return item.label.strip()[:16]
    cleaned = _LABEL_STRIP.sub(" ", title).strip()
    cleaned = " ".join(cleaned.split())
    if cleaned:
        head = _CONCEPT_HEAD.match(cleaned)
        return (head.group(0) if head else cleaned)[:16]
    body = _LABEL_STRIP.sub(" ", text).strip()
    return (" ".join(body.split())[:16] or "未命名主题")


@dataclass
class ObservationEngine:
    """五层判定器。同一输入（含增长历史）永远产出同一结果。"""

    promote_threshold: float = PROMOTE_THRESHOLD
    min_evidence_for_candidate: int = MIN_EVIDENCE_FOR_CANDIDATE

    # ------------------------------------------------------------ 各层

    @staticmethod
    def _top_domain(report: RecognitionReport):
        return report.domains[0] if report.domains else None

    def _semantic_distance(self, report: RecognitionReport, text: str) -> LayerVerdict:
        top = self._top_domain(report)
        if top is None:
            return LayerVerdict(
                layer="semantic_distance",
                score=1.0,
                reason="未命中任何现有领域标记，语义上与现有体系不邻接",
            )
        score = round(max(0.0, 1.0 - top.confidence), 4)
        return LayerVerdict(
            layer="semantic_distance",
            score=score,
            reason=f"最相近领域「{top.name}」相似度 {top.confidence:.2f}，语义距离 {score:.2f}",
            evidence=top.evidence,
        )

    @staticmethod
    def _new_concept_vs_combination(report: RecognitionReport) -> LayerVerdict:
        count = len(report.domains)
        score = round(max(0.2, 1.0 - 0.35 * count), 4)
        if count == 0:
            reason = "现有领域无任何组合可覆盖这段内容"
        elif count == 1:
            reason = "仅与单一现有领域沾边，仍需判断是「新概念」还是「该领域的一部分」"
        else:
            reason = f"同时命中 {count} 个现有领域，更像已有领域的概念组合而非新概念"
        return LayerVerdict(
            layer="new_concept_vs_combination",
            score=score,
            reason=reason,
            evidence=tuple(item.name for item in report.domains),
        )

    def _explanation_cost(self, report: RecognitionReport) -> LayerVerdict:
        top = self._top_domain(report)
        if top is None:
            return LayerVerdict(
                layer="explanation_cost",
                score=0.9,
                reason="现有体系没有任何切入点，解释成本高",
            )
        if top.confidence >= 0.8:
            score, note = 0.25, "现有领域可低成本解释"
        elif top.confidence >= 0.6:
            score, note = 0.5, "现有领域勉强可解释，需要补充说明"
        elif top.confidence >= 0.45:
            score, note = 0.7, "现有领域解释牵强，需要额外背景"
        else:
            score, note = 0.9, "现有领域置信度低于阈值，解释成本高"
        return LayerVerdict(
            layer="explanation_cost",
            score=score,
            reason=f"{note}（「{top.name}」置信度 {top.confidence:.2f}）",
            evidence=top.evidence,
        )

    @staticmethod
    def _independence(report: RecognitionReport, text: str) -> LayerVerdict:
        score = 0.25
        notes: list[str] = ["基础独立性 0.25"]
        if len(text) >= 60:
            score += 0.15
            notes.append("正文长度足够承载独立议题")
        if report.types:
            gain = 0.12 * min(len(report.types), 3)
            score += gain
            notes.append(f"识别到 {len(report.types)} 类信息属性")
        if report.concepts:
            score += 0.15
            notes.append(f"含 {len(report.concepts)} 个专名/术语")
        score = round(min(0.95, score), 4)
        return LayerVerdict(
            layer="independence",
            score=score,
            reason="；".join(notes),
            evidence=tuple(item.label for item in report.concepts[:3]),
        )

    @staticmethod
    def _growth_potential(*, report: RecognitionReport, evidence_count: int) -> LayerVerdict:
        score = 0.3 + 0.15 * max(0, evidence_count - 1)
        notes = [f"累计证据 {evidence_count} 条"]
        if report.temporal.label in {"short_term", "long_term"}:
            score += 0.2
            notes.append("内容带持续性时间线索，可能反复出现")
        score = round(min(0.95, score), 4)
        return LayerVerdict(
            layer="growth_potential",
            score=score,
            reason="；".join(notes),
        )

    # ------------------------------------------------------------ 汇总

    def evaluate(
        self,
        *,
        report: RecognitionReport,
        text: str,
        prior_evidence_count: int = 0,
    ) -> tuple[LayerVerdict, ...]:
        """产出五层判定。`prior_evidence_count` 为该主题此前累计的证据条数（不含本次）。"""
        verdicts = (
            self._semantic_distance(report, text),
            self._new_concept_vs_combination(report),
            self._explanation_cost(report),
            self._independence(report, text),
            self._growth_potential(report=report, evidence_count=prior_evidence_count + 1),
        )
        ordered = {item.layer: item for item in verdicts}
        return tuple(ordered[name] for name in FIVE_LAYERS)

    @staticmethod
    def aggregate(layers: Sequence[LayerVerdict]) -> float:
        """按 LAYER_WEIGHTS 加权求和。缺层按 0 计，权重重新归一化。"""
        total_weight = 0.0
        accumulated = 0.0
        for item in layers:
            weight = LAYER_WEIGHTS.get(item.layer, 0.0)
            if weight <= 0.0:
                continue
            accumulated += item.score * weight
            total_weight += weight
        if total_weight <= 0.0:
            return 0.0
        return round(accumulated / total_weight, 4)

    def decide_state(self, *, overall: float, evidence_count: int) -> str:
        """单次出现的主题永远留在 observation —— 新关键词 ≠ 新领域。"""
        if evidence_count >= self.min_evidence_for_candidate and overall >= self.promote_threshold:
            return "candidate"
        return "observation"

    def summarize(self, layers: Sequence[LayerVerdict], *, overall: float, state: str) -> str:
        weakest = min(layers, key=lambda item: item.score)
        strongest = max(layers, key=lambda item: item.score)
        return (
            f"五层加权 {overall:.2f} → 状态 {state}；"
            f"最强信号「{LAYER_LABELS.get(strongest.layer, strongest.layer)}」{strongest.score:.2f}；"
            f"最弱「{LAYER_LABELS.get(weakest.layer, weakest.layer)}」{weakest.score:.2f}"
        )


@dataclass
class DomainObservationService:
    """把识别报告接进观察区与注册表。"""

    store: StoreLike
    engine: ObservationEngine = field(default_factory=ObservationEngine)

    # ------------------------------------------------------- 观察区写入

    def observe(
        self,
        report: RecognitionReport,
        text: str,
        *,
        title: str = "",
        object_id: str = "",
        moment: datetime | None = None,
    ) -> TopicObservation | None:
        """`unknown_topic` 时写入/累计观察记录；否则返回 None（不改动观察区）。"""
        if not (report.observation_detected or report.new_domain_detected):
            return None

        label = propose_topic_label(title=title, text=text, report=report)
        resolved_id = object_id or report.object_id
        existing = self.store.get_topic(label)

        prior_ids: tuple[str, ...] = ()
        prior_growth: dict[str, int] = {}
        prior_state = "observation"
        if existing is not None:
            observation = _topic_from_row(existing)
            prior_ids = observation.object_ids
            prior_growth = dict(observation.growth)
            prior_state = observation.state

        layers = self.engine.evaluate(
            report=report,
            text=text,
            prior_evidence_count=len(prior_ids),
        )
        overall = self.engine.aggregate(layers)

        object_ids = prior_ids if resolved_id in prior_ids else prior_ids + (resolved_id,)
        evidence_count = len(object_ids)

        growth = dict(prior_growth)
        key = week_key(moment)
        growth[key] = growth.get(key, 0) + 1

        target_state = self.engine.decide_state(overall=overall, evidence_count=evidence_count)
        # 已确认/已拒绝的主题不由本方法回退，交给人工流程
        if prior_state in {"confirmed", "rejected", "merged"}:
            target_state = prior_state

        observation = TopicObservation(
            label=label,
            state=target_state,
            layers=layers,
            object_ids=object_ids,
            growth=growth,
            confidence=overall,
            reason=self.engine.summarize(layers, overall=overall, state=target_state),
        )
        self.store.upsert_topic(observation)
        return observation

    # ------------------------------------------------------- 人工晋升

    def promote_topic(self, label: str, *, actor: str) -> DomainRecord:
        """把观察区主题升为 **candidate** 领域（仍是建议态，不参与自动分类）。"""
        if not actor.strip():
            raise ValueError("promote_topic requires an actor")
        current = self.store.get_topic(label)
        if current is None:
            raise ValueError(f"unknown topic: {label}")
        observation = _topic_from_row(current)
        if observation.state in {"confirmed", "rejected", "merged"}:
            raise ValueError(f"topic {label} is already {observation.state}")
        if self.store.get_domain(label) is not None:
            raise ValueError(f"domain already exists: {label}")

        record = DomainRecord(
            name=label,
            state="candidate",
            promoted_from=observation.resolved_topic_id,
            description=f"由观察区晋升，累计证据 {len(observation.object_ids)} 条",
            evidence_count=len(observation.object_ids),
            confidence=observation.confidence,
            evidence=observation.object_ids[:10],
            reason=observation.reason,
        )
        self.store.upsert_domain(record, actor=actor)
        if observation.state != "candidate":
            self.store.transition_topic(label, "candidate")
        return record

    def confirm_domain(self, name: str, *, actor: str) -> str:
        """人工确认领域。**只能由人调用**：AI 不得自行落 `confirmed`（ADR-008 决策 5）。"""
        if not actor.strip():
            raise ValueError("confirm_domain requires a human actor")
        return self.store.transition_domain(name, "confirmed", actor=actor)

    def reject_domain(self, name: str, *, actor: str) -> str:
        if not actor.strip():
            raise ValueError("reject_domain requires an actor")
        return self.store.transition_domain(name, "rejected", actor=actor)

    def merge_domain(self, source: str, target: str, *, actor: str) -> str:
        if not actor.strip():
            raise ValueError("merge_domain requires an actor")
        return self.store.merge_domains(source, target, actor=actor)

    # ------------------------------------------------------- 建议视图

    def suggested_promotions(
        self, *, min_evidence: int = MIN_EVIDENCE_FOR_SUGGESTION
    ) -> list[dict[str, Any]]:
        """列出可提交人工确认的观察区主题。**只读，不产生任何写操作。**"""
        out: list[dict[str, Any]] = []
        for row in self.store.list_topics(state="candidate"):
            observation = _topic_from_row(row)
            if len(observation.object_ids) < min_evidence:
                continue
            out.append(
                {
                    "topic_id": observation.resolved_topic_id,
                    "label": observation.label,
                    "confidence": observation.confidence,
                    "evidence_count": len(observation.object_ids),
                    "object_ids": list(observation.object_ids),
                    "reason": observation.reason,
                    "action": "await_human_confirmation",
                }
            )
        out.sort(key=lambda item: (-item["confidence"], -item["evidence_count"], item["label"]))
        return out

    def unknown_backlog(self) -> list[dict[str, Any]]:
        """仅单次出现的观察项——**不得**据此创建领域，仅供人回看。"""
        return [_topic_view(row) for row in self.store.list_topics(state="observation")]

    def verdict_table(self, label: str) -> list[dict[str, Any]]:
        current = self.store.get_topic(label)
        if current is None:
            raise ValueError(f"unknown topic: {label}")
        return [item.to_dict() for item in _topic_from_row(current).layers]

    # ------------------------------------------------------- 合并建议（只读）

    def merge_suggestions(
        self,
        *,
        similarity_threshold: float = MERGE_SIMILARITY_THRESHOLD,
        containment_threshold: float = MERGE_CONTAINMENT_THRESHOLD,
    ) -> list[dict[str, Any]]:
        """发现名称层面疑似重复的领域，产出**建议**。

        边界（重要）：本方法**只读**，不合并、不改名、不删除。`AI Agent` / `AI Agents` /
        `Agent` 这类字面近似可以自动发现；`智能代理` 与 `Agent` 这种**纯语义**同义需要
        模型或人工判断，本方法**不猜**（宁可不报，也不错并）。
        """
        rows = self.store.list_domains()
        items: list[dict[str, Any]] = []
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            items.append(
                {
                    "name": name,
                    "state": str(row.get("state", "")),
                    "normalized": normalize_domain_name(name),
                }
            )
        items.sort(key=lambda item: item["name"])

        suggestions: list[dict[str, Any]] = []
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                left_norm, right_norm = left["normalized"], right["normalized"]
                ratio = 0.0
                reason = ""
                if left_norm and left_norm == right_norm:
                    ratio, reason = 1.0, "规范化后完全相同（仅大小写/空格/连字符差异）"
                else:
                    ratio = round(SequenceMatcher(None, left_norm, right_norm).ratio(), 4)
                    if ratio >= similarity_threshold:
                        reason = "字符序列高度相似"
                    else:
                        shorter, longer = sorted((left_norm, right_norm), key=len)
                        if (
                            len(shorter) >= 4
                            and shorter in longer
                            and (longer.startswith(shorter) or longer.endswith(shorter))
                        ):
                            containment = round(len(shorter) / len(longer), 4)
                            if containment >= containment_threshold:
                                ratio, reason = containment, "一个名称是另一个的前缀/后缀"
                if not reason:
                    continue
                suggestions.append(
                    {
                        "left": left["name"],
                        "right": right["name"],
                        "left_state": left["state"],
                        "right_state": right["state"],
                        "similarity": ratio,
                        "reason": reason,
                        "action": "await_human_confirmation",
                        "note": "AI 只给建议，不自动合并；请在人工确认后用 merge_domain(source, target)",
                    }
                )
        suggestions.sort(key=lambda item: (-item["similarity"], item["left"], item["right"]))
        return suggestions


def _topic_from_row(row: dict[str, Any]) -> TopicObservation:
    """从行还原 TopicObservation。

    注意：本模块刻意不复用 `store._hydrate_topic`，以便在测试中用最简 StoreLike 替身；
    两处都接受 raw JSON 与已解码值，行为一致。
    """

    def _load(value: Any, default: Any) -> Any:
        if value in (None, ""):
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    layers = tuple(
        LayerVerdict(
            layer=str(item["layer"]),
            score=float(item["score"]),
            reason=str(item.get("reason", "")),
            evidence=tuple(item.get("evidence") or ()),
        )
        for item in _load(row.get("layers_json", row.get("layers")), [])
    )
    return TopicObservation(
        label=str(row["label"]),
        state=str(row.get("state", "observation")),
        layers=layers,
        object_ids=tuple(_load(row.get("object_ids_json", row.get("object_ids")), [])),
        growth=dict(_load(row.get("growth_json", row.get("growth")), {})),
        confidence=float(row.get("confidence", 0.0) or 0.0),
        reason=str(row.get("reason", "") or ""),
        topic_id=str(row.get("topic_id", "") or ""),
    )


def _topic_view(row: dict[str, Any]) -> dict[str, Any]:
    observation = _topic_from_row(row)
    return {
        "topic_id": observation.resolved_topic_id,
        "label": observation.label,
        "state": observation.state,
        "confidence": observation.confidence,
        "evidence_count": len(observation.object_ids),
        "growth": dict(observation.growth),
        "reason": observation.reason,
    }


# --------------------------------------------------------------- 领域种子


def load_initial_domains(schema_path: Path | None = None) -> tuple[str, ...]:
    """从 Schema 读取初始领域清单。**领域清单的唯一来源是 Schema，不是代码常量。**"""
    path = schema_path or DOMAIN_REGISTRY_SCHEMA
    if not path.is_file():
        raise FileNotFoundError(f"找不到领域注册表 Schema: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = payload.get("initial_domains")
    if not isinstance(names, list) or not names:
        raise ValueError(f"{path} 缺少非空的 initial_domains")
    return tuple(str(item).strip() for item in names if str(item).strip())


def seed_initial_domains(
    store: StoreLike,
    *,
    schema_path: Path | None = None,
    actor: str = SEED_ACTOR,
) -> tuple[str, ...]:
    """把 Schema 声明的初始领域落进注册表（幂等）。

    初始领域被落为 `confirmed`：这份清单来自 Schema 且已经人工审定，
    来源记为 `actor`，可审计。**新增**领域仍必须走人工确认，不受此函数影响。
    """
    names = load_initial_domains(schema_path)
    seeded_at = datetime.now(timezone.utc).isoformat()
    for name in names:
        if store.get_domain(name) is not None:
            continue
        store.upsert_domain(
            DomainRecord(
                name=name,
                state="confirmed",
                description="初始领域，来自 DomainRegistry.json",
                confirmed_by=actor,
                confirmed_at=seeded_at,
                reason="Schema 声明的 initial_domains，非识别产出",
            ),
            actor=actor,
        )
    return names


def resolve_known_domains(
    store: StoreLike,
    *,
    schema_path: Path | None = None,
    seed_if_empty: bool = True,
) -> tuple[str, ...]:
    """取当前可用的已确认领域。注册表为空且允许时，按 Schema 播种初始领域。

    注意：本函数**可能写库**（仅限首次播种），因为不播种就无法做任何分类；
    不需要写入时传 `seed_if_empty=False`。
    """
    names = tuple(row["name"] for row in store.list_domains(state="confirmed"))
    if names or not seed_if_empty:
        return names
    return seed_initial_domains(store, schema_path=schema_path)
