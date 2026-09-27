"""笔记主题归档编排 —— 把「笔记」按**领域主题路径**挂进知识库。

用户已选定方案 **(b) 主题聚合路径**：
按主题建路径（如 `AI`），**同主题的多篇笔记挂到同一路径**，靠标题/搜索区分。
所以此处**不建日期文件夹、不建「一篇一格」路径**。

本模块是**唯一**会把笔记写进 IMA 知识库的编排点。它明确做一件有副作用的事
（挂载笔记），因此**不被 `InformationPipeline` 隐式调用**，必须由调用方显式触发——
与 `agents/information_pipeline.py` 的立场一致（那里「只产出建议，不写外部系统」）。

路径来源：`information_system.taxonomy`，领域一律取自 DomainRegistry，
**未确认领域与未知主题都不会被强行归类**。

成本模型（交付前审查后补记，别当没看见）
--------------------------------------
单次挂载最多 2 类网络动作：**解析路径**（每级 1 次列举）+ **查重**（目标目录 1 次列举）。
若批量 N 篇各跑一遍，就是 ~2N 次调用，遇到限频会很慢。
故批量入口 `mount_notes_by_theme` 内部带一个 **run 级缓存** `TaxonomyRunCache`：
路径只解析一次、目标目录的「已挂载笔记索引」只拉一次并在挂载后增量更新。
**缓存不跨运行复用**——跨运行会看到陈旧目录，宁可慢一次也不要错一次。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from information_system.recognition import RuleBasedBackend
from information_system.taxonomy import (
    UNCLASSIFIED_SEGMENT,
    confirmed_domain_names,
    decide_segments,
    format_path,
    is_unclassified,
)

# note_id 的最短可信长度。真实 note_id 是**定长 16 位数字**，
# 定长意味着 `startswith` 与「前 16 位相等」等价 → 不存在「一个 id 是另一个的前缀」的误判。
# 这个下限只用于挡住手工构造的短 id：短 id 下 startswith 会假阳性，
# 而假阳性会**误判为已挂载从而漏挂**（丢数据），比重复挂载更糟，故宁可判为未挂载。
MIN_NOTE_ID_LENGTH = 12


@dataclass
class TaxonomyRunCache:
    """一次批量运行内的缓存。**不得跨运行复用**（会看到陈旧目录）。

    - `paths`：路径段元组 → 最深层 folder_id
    - `mounted`：folder_id → 该目录下已见到的 media_id 集合（增量维护）
    """

    paths: dict[tuple[str, ...], str] = field(default_factory=dict)
    mounted: dict[str, set[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ThemeMountResult:
    """一次主题挂载的结果。"""

    knowledge_base_id: str
    note_id: str
    title: str
    segments: tuple[str, ...]
    folder_id: str
    media_id: str
    mounted: bool
    skipped_reason: str = ""

    @property
    def path(self) -> str:
        return format_path(self.segments)

    @property
    def unclassified(self) -> bool:
        return is_unclassified(self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_base_id": self.knowledge_base_id,
            "note_id": self.note_id,
            "title": self.title,
            "path": self.path,
            "segments": list(self.segments),
            "folder_id": self.folder_id,
            "media_id": self.media_id,
            "mounted": self.mounted,
            "unclassified": self.unclassified,
            "skipped_reason": self.skipped_reason,
        }


def suggest_domain(store: Any, *, title: str, text: str) -> str | None:
    """用识别引擎的**确定性规则后端**给出领域建议。

    取不到（`unknown_topic`）时返回 `None`——**刻意不返回最接近的那个**：
    invariant 明确「错误分类比暂时没有分类更危险」，调用方应据此落 `未分类`。
    """
    names = confirmed_domain_names(store)
    if not names:
        return None
    raw = RuleBasedBackend().analyze(
        object_id="", title=title, text=text, known_domains=tuple(names)
    )
    if raw.get("unknown_topic"):
        return None
    ranked = raw.get("domains") or []
    if not ranked:
        return None
    return str(ranked[0][0])


def note_mount_token(note_id: str, media_id: str) -> bool:
    """判断某个知识库条目的 `media_id` 是不是由 `note_id` 挂载而来。

    实测挂载返回形如
    `note_033209398da9751a42b6c3220e604491_75054975109040027505484386931481`——
    前半段是内容指纹，**最后一段以 note_id 开头**（后接另一个内部 id）。
    故判据：按 `_` 切开后，最后一段以 note_id 开头。

    `note_id` 短于 `MIN_NOTE_ID_LENGTH` 时**一律返回 False**（判为未挂载）。
    理由见该常量的注释：短 id 下 startswith 会假阳性，而假阳性会误判为已挂载 → 漏挂丢数据。
    """
    note_id = str(note_id)
    if len(note_id) < MIN_NOTE_ID_LENGTH or not media_id:
        return False
    tail = str(media_id).rsplit("_", 1)[-1]
    return tail.startswith(note_id)


def mount_note_by_theme(
    *,
    adapter: Any,
    store: Any,
    knowledge_base_id: str,
    note_id: str,
    title: str,
    domain_name: str | None = None,
    skip_if_already_mounted: bool = True,
    cache: TaxonomyRunCache | None = None,
) -> ThemeMountResult:
    """把一篇笔记挂进「知识库 / 领域祖先链」路径下。

    - `domain_name=None` → 落 `未分类`（unknown 兜底，不做猜测）。
    - `domain_name` 非法（不在注册表 / 未确认）→ 由 `taxonomy` 抛 `ThemePathError`。
    - 路径**幂等**：`ensure_folder_path` 先查后建，重复挂载不会堆同名文件夹。
    - `skip_if_already_mounted=True`（默认）：目标路径下已存在同 `note_id` 的条目时跳过，
      避免同一篇笔记被重复挂载成一堆条目。
    - `cache`：批量场景传入共享缓存可省掉重复列举；**单次调用不要传**（缓存会陈旧）。
    """
    segments = decide_segments(domains=store.list_domains(), domain_name=domain_name)
    folder_id = _resolve_folder(
        adapter, knowledge_base_id=knowledge_base_id, segments=segments, cache=cache
    )

    if skip_if_already_mounted and _already_mounted(
        adapter,
        knowledge_base_id=knowledge_base_id,
        folder_id=folder_id,
        note_id=note_id,
        cache=cache,
    ):
        return ThemeMountResult(
            knowledge_base_id=knowledge_base_id,
            note_id=note_id,
            title=title,
            segments=segments,
            folder_id=folder_id,
            media_id="",
            mounted=False,
            skipped_reason="该路径下已存在同一 note_id 的条目",
        )

    result = adapter.mount_note_into_knowledge(
        knowledge_base_id=knowledge_base_id,
        note_id=note_id,
        title=title,
        folder_id=folder_id,
    )
    media_id = str((result or {}).get("media_id") or "")
    if cache is not None and media_id:
        # 增量维护本轮索引：下一篇若仍是同一 note_id，就能立刻查到，不必再拉一次目录
        cache.mounted.setdefault(folder_id, set()).add(media_id)
    return ThemeMountResult(
        knowledge_base_id=knowledge_base_id,
        note_id=note_id,
        title=title,
        segments=segments,
        folder_id=folder_id,
        media_id=media_id,
        mounted=True,
    )


def mount_notes_by_theme(
    *,
    adapter: Any,
    store: Any,
    knowledge_base_id: str,
    notes: Iterable[dict[str, Any]],
    derive_domain: bool = False,
) -> list[ThemeMountResult]:
    """批量挂载。`notes` 每项需含 `note_id` / `title`，可选 `domain_name` 与 `content`。

    `derive_domain=True` 时，对没给 `domain_name` 的笔记用 `suggest_domain` 推断；
    推断不出来就落 `未分类`。**注意**：推断是规则后端，不是大模型，可复现、可审计。

    批量内共享 `TaxonomyRunCache`：路径与目录索引各只解析一次，之后 O(1) 命中。
    """
    store_domains = store.list_domains()
    run = TaxonomyRunCache()
    results: list[ThemeMountResult] = []
    for note in notes:
        note_id = str(note.get("note_id") or "").strip()
        if not note_id:
            raise ValueError("notes 中每项都必须带 note_id")
        title = str(note.get("title") or "").strip() or note_id
        domain = note.get("domain_name")
        if derive_domain and not (domain and str(domain).strip()):
            domain = suggest_domain(store, title=title, text=str(note.get("content") or ""))
        results.append(
            _mount_with_domains(
                adapter=adapter,
                domains=store_domains,
                knowledge_base_id=knowledge_base_id,
                note_id=note_id,
                title=title,
                domain_name=domain,
                cache=run,
            )
        )
    return results


def _mount_with_domains(
    *,
    adapter: Any,
    domains: list[dict[str, Any]],
    knowledge_base_id: str,
    note_id: str,
    title: str,
    domain_name: str | None,
    cache: TaxonomyRunCache,
) -> ThemeMountResult:
    """批量专用：领域表只读一次，路径与目录索引都走 run 缓存。"""
    segments = decide_segments(domains=domains, domain_name=domain_name)
    folder_id = _resolve_folder(
        adapter, knowledge_base_id=knowledge_base_id, segments=segments, cache=cache
    )
    if _already_mounted(
        adapter,
        knowledge_base_id=knowledge_base_id,
        folder_id=folder_id,
        note_id=note_id,
        cache=cache,
    ):
        return ThemeMountResult(
            knowledge_base_id=knowledge_base_id,
            note_id=note_id,
            title=title,
            segments=segments,
            folder_id=folder_id,
            media_id="",
            mounted=False,
            skipped_reason="该路径下已存在同一 note_id 的条目",
        )
    result = adapter.mount_note_into_knowledge(
        knowledge_base_id=knowledge_base_id,
        note_id=note_id,
        title=title,
        folder_id=folder_id,
    )
    media_id = str((result or {}).get("media_id") or "")
    if media_id:
        cache.mounted.setdefault(folder_id, set()).add(media_id)
    return ThemeMountResult(
        knowledge_base_id=knowledge_base_id,
        note_id=note_id,
        title=title,
        segments=segments,
        folder_id=folder_id,
        media_id=media_id,
        mounted=True,
    )


def _resolve_folder(
    adapter: Any,
    *,
    knowledge_base_id: str,
    segments: tuple[str, ...],
    cache: TaxonomyRunCache | None,
) -> str:
    if cache is not None and segments in cache.paths:
        return cache.paths[segments]
    folder_id = adapter.ensure_folder_path(
        knowledge_base_id=knowledge_base_id, segments=list(segments)
    )
    if cache is not None:
        cache.paths[segments] = folder_id
    return folder_id


def _already_mounted(
    adapter: Any,
    *,
    knowledge_base_id: str,
    folder_id: str,
    note_id: str,
    cache: TaxonomyRunCache | None,
) -> bool:
    """该目录下是否已有由这篇笔记挂载来的条目。

    有缓存时，每个目录的 media_id 集合只拉一次，之后在本轮内增量维护。
    """
    if cache is not None:
        media_ids = cache.mounted.get(folder_id)
        if media_ids is None:
            media_ids = _scan_media_ids(adapter, knowledge_base_id=knowledge_base_id, folder_id=folder_id)
            cache.mounted[folder_id] = media_ids
    else:
        media_ids = _scan_media_ids(adapter, knowledge_base_id=knowledge_base_id, folder_id=folder_id)
    return any(note_mount_token(note_id, media_id) for media_id in media_ids)


def _scan_media_ids(adapter: Any, *, knowledge_base_id: str, folder_id: str) -> set[str]:
    """把目标目录下的条目 media_id 全量取回（翻页到 is_end）。"""
    collected: set[str] = set()
    cursor = ""
    while True:
        page = adapter.list_items(knowledge_base_id, folder_id=folder_id, cursor=cursor)
        for item in page.get("items") or []:
            media_id = str(item.get("media_id") or item.get("id") or "")
            if media_id:
                collected.add(media_id)
        cursor = str(page.get("next_cursor") or "")
        if page.get("is_end") or not cursor:
            return collected


__all__ = [
    "MIN_NOTE_ID_LENGTH",
    "TaxonomyRunCache",
    "ThemeMountResult",
    "mount_note_by_theme",
    "mount_notes_by_theme",
    "note_mount_token",
    "suggest_domain",
    "UNCLASSIFIED_SEGMENT",
]
