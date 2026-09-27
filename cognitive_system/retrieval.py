"""双源联合检索 + cognitive_id 去重（计划书第三十三/三十四节）。

- 双源并行检索：本地库（权威索引）+ IMA（语义）+ 飞书（结构化），不串行 fallback。
- 合并去重：IMA 标题前缀解析 cognitive_id；飞书记录按「认知ID」字段；
  本地库按主键。同一 cognitive_id 只返回一个 CognitiveContext。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ima_writer import extract_cognitive_id_from_title
from .models import CognitiveAsset
from .store import CognitiveStore


@dataclass(frozen=True)
class RetrievalHit:
    cognitive_id: str
    asset: CognitiveAsset | None
    sources: tuple[str, ...]
    remote: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognitive_id": self.cognitive_id,
            "sources": list(self.sources),
            "asset": self.asset.to_dict() if self.asset else None,
            "remote": [dict(item) for item in self.remote],
        }


class CognitiveRetrieval:
    """统一检索入口：问「要找什么认知资产」，而不是「去哪个库」。"""

    def __init__(
        self,
        store: CognitiveStore,
        *,
        ima_searcher=None,
        feishu_searcher=None,
    ) -> None:
        """`ima_searcher(query) -> list[{"title": ..., ...}]`；
        `feishu_searcher(query) -> list[{"fields": {...}, ...}]`。均可选。"""
        self._store = store
        self._ima_searcher = ima_searcher
        self._feishu_searcher = feishu_searcher

    def search(self, query: str, *, limit: int = 10) -> list[RetrievalHit]:
        query = query.strip()
        if not query:
            return []
        hits: dict[str, RetrievalHit] = {}

        # 1) 本地库（权威索引）
        for asset in self._store.search_assets(query, limit=limit):
            hits[asset.cognitive_id] = RetrievalHit(
                cognitive_id=asset.cognitive_id, asset=asset, sources=("local",)
            )

        # 2) IMA 语义检索
        if self._ima_searcher is not None:
            try:
                items = self._ima_searcher(query) or []
            except Exception:  # noqa: BLE001 —— 检索降级不阻断
                items = []
            for item in items:
                title = str(item.get("title", ""))
                cognitive_id = extract_cognitive_id_from_title(title)
                if not cognitive_id:
                    continue  # 无 cognitive_id 的 IMA 条目不参与合并（避免撞库）
                if cognitive_id in hits:
                    hit = hits[cognitive_id]
                    hits[cognitive_id] = RetrievalHit(
                        cognitive_id=cognitive_id,
                        asset=hit.asset,
                        sources=tuple(dict.fromkeys((*hit.sources, "ima"))),
                        remote=(*hit.remote, item),
                    )
                else:
                    hits[cognitive_id] = RetrievalHit(
                        cognitive_id=cognitive_id, asset=None, sources=("ima",), remote=(item,)
                    )

        # 3) 飞书结构化检索
        if self._feishu_searcher is not None:
            try:
                records = self._feishu_searcher(query) or []
            except Exception:  # noqa: BLE001
                records = []
            for record in records:
                fields = record.get("fields", {}) if isinstance(record, dict) else {}
                cognitive_id = str(fields.get("认知ID", "") or "")
                if not cognitive_id:
                    continue
                if cognitive_id in hits:
                    hit = hits[cognitive_id]
                    hits[cognitive_id] = RetrievalHit(
                        cognitive_id=cognitive_id,
                        asset=hit.asset,
                        sources=tuple(dict.fromkeys((*hit.sources, "feishu"))),
                        remote=(*hit.remote, record),
                    )
                else:
                    hits[cognitive_id] = RetrievalHit(
                        cognitive_id=cognitive_id, asset=None, sources=("feishu",), remote=(record,)
                    )

        ranked = sorted(
            hits.values(),
            key=lambda hit: (
                hit.asset is not None,
                len(hit.sources),
                hit.asset.confidence if hit.asset else 0.0,
            ),
            reverse=True,
        )
        return ranked[:limit]
