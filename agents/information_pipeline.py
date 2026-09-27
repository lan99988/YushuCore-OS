"""信息流编排入口（C6）。

把「拉取 → 落库 → 识别 → 观察区 → 分流建议」串成一条可测的流水线。
**只产出建议，不执行任何写外部系统动作**（不建飞书任务、不写知识库、不改认知 OS）。

依赖方向：agents → information_system / integrations（单向）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from information_system.inbox import IngestOutcome, IngestionPipeline

DEFAULT_PAGE_LIMIT = 50


@dataclass(frozen=True)
class PullSummary:
    """一次 IMA 拉取的结果统计。"""

    scanned: int = 0
    ingested: int = 0
    skipped_unparsed: int = 0
    duplicates: int = 0
    outcomes: tuple[IngestOutcome, ...] = ()
    skipped_titles: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "ingested": self.ingested,
            "skipped_unparsed": self.skipped_unparsed,
            "duplicates": self.duplicates,
            "skipped_titles": list(self.skipped_titles),
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


def sync_ima_to_inbox(
    *,
    adapter: Any,
    knowledge_base_id: str,
    pipeline: IngestionPipeline | None = None,
    store: Any | None = None,
    max_items: int = DEFAULT_PAGE_LIMIT,
    only_parsed: bool = True,
    folder_id: str = "",
) -> PullSummary:
    """从 IMA 知识库拉取条目并落进信息对象库。

    - `only_parsed=True`（默认）跳过仍在解析中的条目：写入是异步的，
      **不假设 `add_knowledge` 后立即可读**（见 ADR-008）。跳过项在摘要里报出，不静默丢弃。
    - 幂等：同一 `media_id` 重复拉取不会产生新对象，计入 `duplicates`。
    """
    if pipeline is None:
        if store is None:
            raise ValueError("sync_ima_to_inbox 需要 pipeline 或 store 之一")
        pipeline = IngestionPipeline(store)

    from integrations.ima import ImaAdapter, PulledItem  # 延迟导入，避免顶层循环依赖

    scanned = 0
    ingested = 0
    skipped_unparsed = 0
    duplicates = 0
    outcomes: list[IngestOutcome] = []
    skipped_titles: list[str] = []
    cursor = ""

    while scanned < max_items:
        page = adapter.list_items(
            knowledge_base_id,
            folder_id=folder_id,
            limit=min(DEFAULT_PAGE_LIMIT, max_items - scanned),
            cursor=cursor,
        )
        items: Iterable[dict[str, Any]] = page.get("items") or []
        batch = 0
        for raw in items:
            if scanned >= max_items:
                break
            batch += 1
            scanned += 1
            pulled = PulledItem.from_api(raw, knowledge_base_id=knowledge_base_id)
            if only_parsed and pulled.media_state is not None and not ImaAdapter.is_parsed(raw):
                skipped_unparsed += 1
                skipped_titles.append(pulled.title)
                continue
            captured = pulled.to_capture()
            outcome = pipeline.ingest(
                source=captured["source"],
                title=captured["title"],
                content=captured["content"],
                source_ref=captured["source_ref"],
                source_container=captured["source_container"],
            )
            if outcome.created:
                ingested += 1
                outcomes.append(outcome)
            else:
                duplicates += 1
        cursor = str(page.get("next_cursor", "") or "")
        if page.get("is_end") or not cursor or batch == 0:
            break

    return PullSummary(
        scanned=scanned,
        ingested=ingested,
        skipped_unparsed=skipped_unparsed,
        duplicates=duplicates,
        outcomes=tuple(outcomes),
        skipped_titles=tuple(skipped_titles),
    )


@dataclass
class InformationPipeline:
    """对外门面：把上面两个动作收敛成一个对象，便于脚本与 Agent 调用。"""

    store: Any
    ingestion: IngestionPipeline | None = None

    def __post_init__(self) -> None:
        if self.ingestion is None:
            self.ingestion = IngestionPipeline(self.store)

    def ingest(self, **kwargs: Any) -> IngestOutcome:
        return self.ingestion.ingest(**kwargs)

    def ingest_ima_knowledge_base(
        self,
        knowledge_base_id: str,
        *,
        adapter: Any | None = None,
        max_items: int = DEFAULT_PAGE_LIMIT,
        only_parsed: bool = True,
    ) -> PullSummary:
        if adapter is None:
            from integrations.ima import ImaAdapter

            adapter = ImaAdapter()
        return sync_ima_to_inbox(
            adapter=adapter,
            knowledge_base_id=knowledge_base_id,
            pipeline=self.ingestion,
            max_items=max_items,
            only_parsed=only_parsed,
        )

    def pending_review(self) -> list[dict[str, Any]]:
        """待人工确认的认知/知识候选 + 观察区升级建议（只读）。"""
        observer = self.ingestion.observer
        topics = observer.suggested_promotions() if observer is not None else []
        objects = [
            {
                "object_id": row["object_id"],
                "title": row["title"],
                "knowledge_level": row["knowledge_level"],
                "cognitive_os_level": row["cognitive_os_level"],
                "recommendation": (row.get("attributes") or {}).get("recommendation", ""),
            }
            for row in self.store.list_objects(decision_state="detected", limit=500)
            if row.get("knowledge_level") != "information" or row.get("cognitive_os_detected")
        ]
        return [{"kind": "topic_promotion", **item} for item in topics] + [
            {"kind": "object_review", **item} for item in objects
        ]
