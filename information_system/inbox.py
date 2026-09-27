"""Inbox 接线：把「外部内容」变成「信息对象 + 判别报告 + 观察区记录」。

这是 C6 编排入口的本地部分，也是 `integrations/capture.py` 的 writer 实现：
任何来源（IMA / 网页 / 手动）只要给出 `source / title / content`，就落进同一个信息对象库，
**不再为每个来源各建一套表**（对应规格 §17 One Source, Multiple Projections）。

边界：
- 本模块只做「落库 + 识别 + 观察区」，**不建飞书任务、不写知识库、不改认知 OS**。
  三流分流只是产出建议，落地动作由人确认后另行执行（ADR-008 决策 5）。
- 正文不落信息对象层：只存 `excerpt` 与 `content_digest`，正文留在来源侧（IMA / 文件）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .models import (
    SOURCE_KINDS,
    InformationObject,
    RecognitionReport,
    content_digest,
)
from .observation import DomainObservationService, resolve_known_domains
from .recognition import DEFAULT_DOMAIN_THRESHOLD, RecognitionEngine

EXCERPT_LIMIT = 200


class IngestError(ValueError):
    """输入不满足信息对象的最低要求。"""


def _excerpt(content: str, limit: int = EXCERPT_LIMIT) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class IngestOutcome:
    """一次入库的结果摘要。可直接序列化给人看。"""

    object_id: str
    created: bool
    source: str
    recommendation: str
    knowledge_level: str
    cognitive_os_level: str
    domains: tuple[str, ...]
    topic_label: str = ""
    topic_state: str = ""
    report: RecognitionReport | None = None
    # 同内容（不同来源）已存在时给出**参考**，不合并、不删改任何一方。
    duplicate_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "created": self.created,
            "source": self.source,
            "recommendation": self.recommendation,
            "knowledge_level": self.knowledge_level,
            "cognitive_os_level": self.cognitive_os_level,
            "domains": list(self.domains),
            "topic_label": self.topic_label,
            "topic_state": self.topic_state,
            "duplicate_of": self.duplicate_of,
        }


@dataclass
class IngestionPipeline:
    """外部内容 → 信息对象库 → 判别报告 → 观察区。"""

    store: Any
    recognizer: RecognitionEngine = field(default_factory=RecognitionEngine)
    observer: DomainObservationService | None = None
    known_domains: tuple[str, ...] = ()
    domain_threshold: float = DEFAULT_DOMAIN_THRESHOLD

    def __post_init__(self) -> None:
        if self.observer is None:
            self.observer = DomainObservationService(self.store)

    # ---------------------------------------------------------------- 内部

    def _resolved_domains(self) -> tuple[str, ...]:
        if self.known_domains:
            return self.known_domains
        return resolve_known_domains(self.store)

    @staticmethod
    def _split_domains(report: RecognitionReport, threshold: float):
        """unknown_topic 时不落任何正式领域，全部降为候选（禁强行归类）。"""
        if report.new_domain_detected or report.observation_detected:
            return (), report.domains
        assigned = tuple(item.name for item in report.domains if item.confidence >= threshold)
        candidates = tuple(item for item in report.domains if item.confidence < threshold)
        return assigned, candidates

    # ---------------------------------------------------------------- 主流程

    def ingest(
        self,
        *,
        source: str,
        title: str,
        content: str,
        source_ref: str = "",
        source_container: str = "",
        correlation_id: str = "",
        moment: datetime | None = None,
    ) -> IngestOutcome:
        if source not in SOURCE_KINDS:
            raise IngestError(f"unsupported source: {source!r}（允许 {sorted(SOURCE_KINDS)}）")
        if not title.strip():
            raise IngestError("title is required")
        if not content.strip():
            raise IngestError("content is required")

        text = content.strip()
        known = self._resolved_domains()

        base = InformationObject(
            source=source,
            title=title.strip(),
            source_ref=source_ref.strip(),
            source_container=source_container.strip(),
            content_digest=content_digest(text),
            excerpt=_excerpt(text),
            correlation_id=correlation_id.strip(),
        )
        object_id, created = self.store.upsert_object(base)
        # 显式记录一次生命周期迁移，保持事件流可审计（captured → inbox）
        self.store.set_lifecycle(object_id, "inbox", actor="ingestion_pipeline")

        report = self.recognizer.recognize(
            base, text, known_domains=known, object_id=object_id, moment=moment
        )
        assigned, candidates = self._split_domains(report, self.domain_threshold)

        attributes: dict[str, Any] = {}
        if report.temporal_detail:
            attributes["temporal"] = dict(report.temporal_detail)

        enriched = InformationObject(
            source=source,
            title=base.title,
            source_ref=base.source_ref,
            source_container=base.source_container,
            content_digest=base.content_digest,
            excerpt=base.excerpt,
            correlation_id=base.correlation_id,
            deadline=report.deadline,
            object_id=object_id,
            status="inbox",
            temporal=report.temporal.label,
            types=tuple(item for item in report.types if isinstance(item, str)),
            knowledge_level=report.knowledge_level,
            cognitive_os_detected=report.cognitive_os_detected,
            cognitive_os_level=report.cognitive_os_level,
            domains=assigned,
            domain_candidates=candidates,
            unknown_topic=report.new_domain_detected,
            concepts=report.concepts,
            relations=report.relations,
            projects=report.projects,
            actions=report.actions,
            attributes=attributes,
            confidence=report.confidence,
            evidence=report.evidence,
            reason=report.reason,
        )
        self.store.upsert_object(enriched)
        self.store.record_report(report)

        # 同内容、不同来源：只追加一条参考事件，**不合并、不删除任何一方**
        duplicate_of = ""
        if created:
            duplicate_of = self._record_duplicate_hint(
                object_id=object_id,
                digest=base.content_digest,
                source=source,
                source_ref=base.source_ref,
            )

        topic_label = ""
        topic_state = ""
        assert self.observer is not None
        observation = self.observer.observe(
            report, text, title=base.title, object_id=object_id, moment=moment
        )
        if observation is not None:
            topic_label = observation.label
            topic_state = observation.state

        return IngestOutcome(
            object_id=object_id,
            created=created,
            source=source,
            recommendation=report.recommendation_action,
            knowledge_level=report.knowledge_level,
            cognitive_os_level=report.cognitive_os_level,
            domains=assigned,
            topic_label=topic_label,
            topic_state=topic_state,
            report=report,
            duplicate_of=duplicate_of,
        )

    # ------------------------------------------------------------ 重复提示

    def _record_duplicate_hint(
        self, *, object_id: str, digest: str, source: str, source_ref: str
    ) -> str:
        """同一正文出现在别处时记录参考事件。返回被参考的 object_id（无则空串）。"""
        if not digest:
            return ""
        finder = getattr(self.store, "find_by_content_digest", None)
        if finder is None:
            return ""
        try:
            others = finder(digest, exclude_object_id=object_id)
        except TypeError:  # 替身 store 只接受位置参数时的兜底
            others = finder(digest)
        for row in others or ():
            if str(row.get("object_id", "")) == object_id:
                continue
            self.store.record_event(
                object_id,
                "duplicate_candidate",
                {
                    "duplicate_of": row.get("object_id", ""),
                    "duplicate_source": row.get("source", ""),
                    "duplicate_source_ref": row.get("source_ref", ""),
                    "self_source": source,
                    "self_source_ref": source_ref,
                    "note": "同内容不同来源，仅供人工参考，未做合并",
                },
                actor="ingestion_pipeline",
            )
            return str(row.get("object_id", ""))
        return ""

    # ---------------------------------------------------------- CaptureAdapter

    def as_capture_writer(self) -> Callable[[dict[str, Any]], IngestOutcome]:
        """返回符合 `CaptureAdapter(writer=...)` 契约的可调用对象。

        `CaptureAdapter` 会把 `destination` 固定为 `00_Inbox`；本写入器把它物化为
        信息对象的 `status=inbox`，即同一个语义的两种表示。
        """

        def _write(item: dict[str, Any]) -> IngestOutcome:
            return self.ingest(
                source=str(item.get("source", "")),
                title=str(item.get("title", "")),
                content=str(item.get("content", "")),
                source_ref=str(item.get("source_ref", "") or ""),
                source_container=str(item.get("source_container", "") or ""),
                correlation_id=str(item.get("correlation_id", "") or ""),
            )

        return _write
