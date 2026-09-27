"""cognitive_id 生成器。

格式：`<PREFIX>-<YYYYMMDD>-<6位序号>`，例 `KNW-20260915-000123`（计划书第三/十二节）。
序号由调用方注入（默认内存自增；生产用 CognitiveStore.next_sequence 保证重启后不重号）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from itertools import count

from .models import COGNITIVE_TYPE_PREFIXES

ID_WIDTH = 6


def format_cognitive_id(prefix: str, date_key: str, sequence: int) -> str:
    return f"{prefix}-{date_key}-{sequence:0{ID_WIDTH}d}"


COGNITIVE_ID_PATTERN = (
    r"^(SRC|NOTE|EXP|KNW|CON|INS|BEL|DEC)-[0-9]{8}-[0-9]{%d}$" % ID_WIDTH
)


class CognitiveIdAllocator:
    """按 (prefix, date) 分配递增序号。

    `sequence_fn(prefix, date_key) -> int` 返回**下一个**可用序号（从 1 开始）。
    默认实现为内存自增（仅用于测试/单进程轻量场景）。
    """

    def __init__(self, sequence_fn: Callable[[str, str], int] | None = None, *, now: Callable[[], datetime] | None = None) -> None:
        self._sequence_fn = sequence_fn or self._make_memory_sequences()
        self._now = now or datetime.now

    @staticmethod
    def _make_memory_sequences() -> Callable[[str, str], int]:
        counters: dict[tuple[str, str], count] = {}

        def next_sequence(prefix: str, date_key: str) -> int:
            return next(counters.setdefault((prefix, date_key), count(1)))

        return next_sequence

    def allocate(self, cognitive_type: str, *, at: datetime | None = None) -> str:
        if cognitive_type not in COGNITIVE_TYPE_PREFIXES:
            raise ValueError(f"非法认知类型: {cognitive_type}")
        moment = at or self._now()
        prefix = COGNITIVE_TYPE_PREFIXES[cognitive_type]
        date_key = f"{moment:%Y%m%d}"
        sequence = self._sequence_fn(prefix, date_key)
        if sequence < 1:
            raise ValueError("序号必须从 1 开始")
        return format_cognitive_id(prefix, date_key, sequence)
