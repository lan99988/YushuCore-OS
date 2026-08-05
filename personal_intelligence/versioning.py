from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import SelfModelSnapshot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SelfModelChange:
    version: int
    before: dict[str, object]
    after: dict[str, object]
    reason: str
    reviewer: str
    created_at: str


class SelfModelVersionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_change(
        self,
        before: SelfModelSnapshot,
        after: SelfModelSnapshot,
        *,
        reason: str,
        reviewer: str,
    ) -> SelfModelChange:
        if not reviewer.strip():
            raise PermissionError("reviewer is required for Self Model change")
        if not reason.strip():
            raise ValueError("reason is required")
        latest = self.latest()
        change = SelfModelChange(
            version=(latest.version + 1) if latest else 1,
            before=asdict(before),
            after=asdict(after),
            reason=reason,
            reviewer=reviewer,
            created_at=_now(),
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(asdict(change), ensure_ascii=False, default=str) + "\n")
        return change

    def list(self) -> tuple[SelfModelChange, ...]:
        if not self.path.exists():
            return ()
        return tuple(
            SelfModelChange(**json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def latest(self) -> SelfModelChange | None:
        changes = self.list()
        return changes[-1] if changes else None
