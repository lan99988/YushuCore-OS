from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_core.models import MemoryEntry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.root / "memory.jsonl"
        self.scope_paths = {
            "system": self.root / "99_System.jsonl",
            "agent": self.root / "08_Agent_Memory.jsonl",
            "personal": self.root / "11_Self_Model.jsonl",
        }
        self._entries: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        if not self.memory_path.exists():
            return
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            self._entries.append(MemoryEntry(**json.loads(line)))

    def record(self, agent_id: str, *, task: str, output: Any, scope: str = "agent") -> MemoryEntry:
        if scope not in {"system", "agent", "personal"}:
            raise ValueError("memory scope must be system, agent, or personal")
        if scope == "personal":
            raise PermissionError("agents cannot write personal memory")
        entry = MemoryEntry(agent_id=agent_id, task=task, output=output, created=_now(), scope=scope)
        self._entries.append(entry)
        with self.memory_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n")
        with self.scope_paths[scope].open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n")
        return entry

    def recent(self, agent_id: str, limit: int | None = None, *, scope: str | None = None) -> list[MemoryEntry]:
        entries = [entry for entry in self._entries if entry.agent_id == agent_id]
        if scope is not None:
            if scope not in {"system", "agent", "personal"}:
                raise ValueError("memory scope must be system, agent, or personal")
            entries = [entry for entry in entries if entry.scope == scope]
        if limit is None:
            return entries
        return entries[-limit:]

    def size(self, agent_id: str, *, scope: str | None = None) -> int:
        return len(self.recent(agent_id, scope=scope))
