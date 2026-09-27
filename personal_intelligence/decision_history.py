from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

from .models import DecisionRecord, PersonalRuleStatus, PersonalRuleTarget
from .rule_candidates import PersonalRuleCandidateStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionHistoryStore:
    """Append-only history; it never edits Personal Memory or prior decisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.path.with_name(f"{self.path.stem}.audit.jsonl")
        self._rule_store: PersonalRuleCandidateStore | None = None

    def bind_rule_store(self, rule_store: PersonalRuleCandidateStore) -> None:
        if not isinstance(rule_store, PersonalRuleCandidateStore):
            raise TypeError("rule_store must be a PersonalRuleCandidateStore")
        if self._rule_store is not None and self._rule_store is not rule_store:
            raise ValueError("decision history is already bound to another rule store")
        self._rule_store = rule_store

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
        scope: tuple[str, ...] | list[str] = (),
        applied_rule_ids: tuple[str, ...] | list[str] = (),
        rule_target: str | PersonalRuleTarget = PersonalRuleTarget.DECISION_GUIDANCE,
    ) -> DecisionRecord:
        normalized_scope = tuple(dict.fromkeys(part.strip() for part in scope if part.strip()))
        target = PersonalRuleTarget(rule_target)
        rule_ids = tuple(applied_rule_ids)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("duplicate applied rule_id")
        for rule_id in rule_ids:
            if not re.fullmatch(r"RULE-[A-Za-z0-9]{32}", rule_id):
                raise ValueError("invalid rule_id")
        eligible_ids = set()
        if rule_ids:
            if self._rule_store is None:
                raise ValueError("applied rules require a bound rule store")
            eligible_ids = {
                rule.rule_id
                for rule in self._rule_store.active_rules(scope=normalized_scope, target=target)
                if rule.status is PersonalRuleStatus.ACTIVE
            }
            if not set(rule_ids).issubset(eligible_ids):
                raise ValueError("applied rule is not active for this scope and target")
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
            rule_ids=rule_ids,
            scope=normalized_scope,
            rule_target=target.value,
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
                value["rule_ids"] = tuple(value.get("rule_ids", ()))
                value["scope"] = tuple(value.get("scope", ()))
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
            "rule_ids": record.rule_ids,
            "rule_target": record.rule_target,
            "timestamp": record.created_at,
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
