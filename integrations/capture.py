from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4


class CaptureAdapter:
    """Routes external content into Inbox review through an injected writer.

    `source_ref` / `source_container` 为可选来源标识（如 IMA 的 media_id 与知识库 ID）。
    信息对象库用 `source_ref` 做幂等键，因此拉取类来源应尽量填上；
    不填时由正文指纹兜底（见 `information_system.models.compute_source_key`）。
    """

    def __init__(self, *, writer: Callable[[dict[str, object]], object]) -> None:
        if not callable(writer):
            raise ValueError("writer must be callable")
        self._writer = writer

    def capture(
        self,
        *,
        source: str,
        content: str,
        title: str,
        correlation_id: str = "",
        source_ref: str = "",
        source_container: str = "",
    ) -> dict[str, object]:
        if not source.strip() or not content.strip() or not title.strip():
            raise ValueError("source, title, and content are required")
        item = {
            "capture_id": f"CAP-{uuid4().hex}",
            "source": source,
            "title": title.strip(),
            "content": content,
            "source_ref": source_ref.strip(),
            "source_container": source_container.strip(),
            "destination": "00_Inbox",
            "status": "review_required",
            "correlation_id": correlation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._writer(dict(item))
        return item
