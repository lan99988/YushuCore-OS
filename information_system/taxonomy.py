"""主题路径（Taxonomy）——把「领域」映射成知识库里的文件夹路径。

设计立场（四条，均源自 `DomainRegistry.json` 的 invariants，勿淡化）
------------------------------------------------------------------
1. **领域一律来自 DomainRegistry**。本模块**不持有任何领域清单**——
   对应 invariant：「domain 取值必须来自本注册表，代码中不得出现硬编码领域列表」。
2. **只有 `state=confirmed` 的领域可参与自动分类**——
   对应 invariant：「state=candidate 的领域不得参与自动分类，只能作为建议呈现」。
3. **无法自然容纳时必须落 unknown**——对应 invariant：
   「错误分类比暂时没有分类更危险：无法自然容纳时必须先落 unknown，不得强行归入现有领域」。
   本模块用 `未分类` 这一**保留段**表达 unknown，绝不把未知主题硬塞进现有领域。
4. **路径 = 该领域的祖先链**（沿 `parent_id` 逐级上溯）。所以领域体系一旦长出子领域
   （如「生活 → 财务」），路径**自动**变成两级，**无需改代码**。

为什么路径取祖先链而不是「领域 + 主题」：用户已选 (b) 主题聚合路径
（`库/技术/AI`，同主题多篇笔记挂同一路径，靠标题/搜索区分）。
领域体系本身就是用户世界模型的分层投影，直接复用即可，不另造一套主题树。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# 未知主题的**保留段**。刻意用中文常见词而非 `_unknown`：
# 它会出现在用户的文件夹列表里，必须是「人一眼就懂」的。
UNCLASSIFIED_SEGMENT = "未分类"

# 展示用分隔符。**不用于 IMA 请求**——IMA 的层级由 folder_id 父子关系表达，与名字无关。
PATH_SEPARATOR = "/"

# IMA 文件夹名的服务端上限（`create_folder` 实测校验 255）。
MAX_SEGMENT_LENGTH = 255

# 领域状态中唯一允许参与自动分类的取值。
AUTOMATIC_DOMAIN_STATE = "confirmed"

# 路径段里禁止出现的字符：会把展示用的 `/` 层级搞歧义。
FORBIDDEN_IN_SEGMENT = ("/", "\\")


class ThemePathError(ValueError):
    """主题路径无法确定。"""


@dataclass(frozen=True)
class DomainIndex:
    """领域注册表的只读索引。`by_id` 用于沿 parent_id 上溯。"""

    by_name: Mapping[str, dict[str, Any]]
    by_id: Mapping[str, dict[str, Any]]

    @classmethod
    def build(cls, domains: Iterable[dict[str, Any]]) -> "DomainIndex":
        by_name: dict[str, dict[str, Any]] = {}
        by_id: dict[str, dict[str, Any]] = {}
        for row in domains:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            by_name[name] = dict(row)
            domain_id = str(row.get("domain_id") or "").strip()
            if domain_id:
                by_id[domain_id] = dict(row)
        return cls(by_name=by_name, by_id=by_id)


def _check_segment(segment: str) -> str:
    cleaned = str(segment).strip()
    if not cleaned:
        raise ThemePathError("路径段不能为空")
    if len(cleaned) > MAX_SEGMENT_LENGTH:
        raise ThemePathError(f"路径段不得超过 {MAX_SEGMENT_LENGTH} 字符：{cleaned[:20]}…")
    for bad in FORBIDDEN_IN_SEGMENT:
        if bad in cleaned:
            raise ThemePathError(f"路径段不得含 {bad!r}（会与层级分隔符混淆）：{cleaned!r}")
    return cleaned


def domain_chain(index: DomainIndex, domain_name: str) -> tuple[str, ...]:
    """把一个领域名展开成**从根到该领域**的祖先链。

    只接受 `state=confirmed` 的领域：`candidate` / `observation` 一律拒绝
    （invariant：「candidate 不得参与自动分类」）。

    领域不存在时抛 `ThemePathError`——**刻意不返回空路径**，
    避免调用方误把「没找到」当成「落根目录」。
    """
    name = str(domain_name or "").strip()
    if not name:
        raise ThemePathError("领域名不能为空")

    row = index.by_name.get(name)
    if row is None:
        raise ThemePathError(f"领域「{name}」不在 DomainRegistry 中——领域清单必须来自注册表")
    state = str(row.get("state") or "")
    if state != AUTOMATIC_DOMAIN_STATE:
        raise ThemePathError(
            f"领域「{name}」当前 state={state!r}，只有 {AUTOMATIC_DOMAIN_STATE!r} 可参与自动分类"
        )

    chain: list[str] = [_check_segment(name)]
    seen_ids: set[str] = set()
    current = row
    while True:
        parent_id = str(current.get("parent_id") or "").strip()
        domain_id = str(current.get("domain_id") or "").strip()
        if domain_id:
            if domain_id in seen_ids:
                raise ThemePathError(f"领域「{name}」的 parent_id 链存在环，请先修注册表")
            seen_ids.add(domain_id)
        if not parent_id:
            break
        parent = index.by_id.get(parent_id)
        if parent is None:
            raise ThemePathError(
                f"领域「{name}」的父领域 id={parent_id!r} 在注册表中不存在"
            )
        # 祖先也必须已确认：否则会出现「确认的领域」挂在一个「候选领域」下面的路径，
        # 等于让 candidate 间接参与了自动分类（违反 invariant）。
        parent_state = str(parent.get("state") or "")
        if parent_state != AUTOMATIC_DOMAIN_STATE:
            raise ThemePathError(
                f"领域「{name}」的父领域「{parent.get('name')}」state={parent_state!r}，"
                f"祖先链含未确认领域，拒绝自动分类"
            )
        chain.append(_check_segment(str(parent.get("name") or "")))
        current = parent

    chain.reverse()
    return tuple(chain)


def decide_segments(
    *,
    domains: Iterable[dict[str, Any]],
    domain_name: str | None = None,
    unclassified: str = UNCLASSIFIED_SEGMENT,
) -> tuple[str, ...]:
    """决定一篇内容应该落进哪条路径。

    - `domain_name` 为空/空白 → 落 `未分类`（unknown 语义，**不做任何猜测**）。
    - `domain_name` 给了但不在注册表 / 非 confirmed → **抛错**，不静默降级。
      理由：调用方显式报了领域却被拒，是**能修复的 bug**；而静默塞进「未分类」
      会让 bug 变成数据噪声（invariant：「错误分类比暂时没有分类更危险」，
      反向也成立——**静默丢信息同样危险**）。
    """
    if domain_name is None or not str(domain_name).strip():
        return (_check_segment(unclassified),)
    return domain_chain(DomainIndex.build(domains), str(domain_name))


def confirmed_domain_names(store: Any) -> tuple[str, ...]:
    """从注册表读**已确认**领域名。这是自动分类唯一合法的领域来源。"""
    rows = store.list_domains(state=AUTOMATIC_DOMAIN_STATE)
    return tuple(
        sorted(
            str(row.get("name")).strip()
            for row in rows
            if str(row.get("name") or "").strip()
        )
    )


def format_path(segments: Iterable[str]) -> str:
    """把路径段拼成展示字符串（如 `AI/提示词`）。仅用于日志与说明。"""
    return PATH_SEPARATOR.join(str(segment) for segment in segments)


def is_unclassified(segments: Iterable[str], *, unclassified: str = UNCLASSIFIED_SEGMENT) -> bool:
    """判断路径是否为 unknown 兜底路径。"""
    parts = tuple(segments)
    return len(parts) == 1 and parts[0] == unclassified
