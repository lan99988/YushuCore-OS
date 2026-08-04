from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeLogger:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"

    def write(self, event: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
