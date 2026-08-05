from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4


class CaptureAdapter:
    """Routes external content into Inbox review through an injected writer."""

    def __init__(self, *, writer: Callable[[dict[str, object]], object]) -> None:
        if not callable(writer):
            raise ValueError("writer must be callable")
        self._writer = writer

    def capture(self, *, source: str, content: str, title: str, correlation_id: str = "") -> dict[str, object]:
        if not source.strip() or not content.strip() or not title.strip():
            raise ValueError("source, title, and content are required")
        item = {
            "capture_id": f"CAP-{uuid4().hex}",
            "source": source,
            "title": title.strip(),
            "content": content,
            "destination": "00_Inbox",
            "status": "review_required",
            "correlation_id": correlation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._writer(dict(item))
        return item
