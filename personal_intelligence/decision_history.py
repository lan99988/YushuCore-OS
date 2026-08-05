from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import DecisionRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionHistoryStore:
    """Append-only history; it never edits Personal Memory or prior decisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.path.with_name(f"{self.path.stem}.audit.jsonl")

    def append(
        self,
        *,
        decision: str,
        context: str,
        options: list[str] | tuple[str, ...],
        chosen_action: str,
        reason: str,
        evidence: list[str] | tuple[str, ...] = (),
        outcome: str = "",
        reflection: str = "",
        agent_id: str = "",
        reviewer: str = "",
        correlation_id: str = "",
    ) -> DecisionRecord:
        record = DecisionRecord(
            decision_id=f"DEC-{uuid4().hex}",
            decision=decision,
            context=context,
            options=tuple(options),
            chosen_action=chosen_action,
            reason=reason,
            evidence=tuple(evidence),
            outcome=outcome,
            reflection=reflection,
            agent_id=agent_id,
            reviewer=reviewer,
            correlation_id=correlation_id,
            created_at=_now(),
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
        self._audit(record)
        return record

    def list(self) -> tuple[DecisionRecord, ...]:
        if not self.path.exists():
            return ()
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                value["options"] = tuple(value.get("options", ()))
                value["evidence"] = tuple(value.get("evidence", ()))
                records.append(DecisionRecord(**value))
        return tuple(records)

    def update(self, decision_id: str, changes: dict[str, object]) -> None:
        raise PermissionError("decision history is append-only")

    def audit_events(self) -> list[dict[str, object]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _audit(self, record: DecisionRecord) -> None:
        event = {
            "action": "decision_recorded",
            "decision_id": record.decision_id,
            "agent_id": record.agent_id,
            "correlation_id": record.correlation_id,
            "timestamp": record.created_at,
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
