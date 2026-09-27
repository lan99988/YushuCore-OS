from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime_core.events import safe_event_snapshot


class RuntimeLogger:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"

    def write(self, event: dict[str, Any]) -> None:
        safe_event = safe_event_snapshot(event)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(safe_event, ensure_ascii=False, default=str) + "\n")
