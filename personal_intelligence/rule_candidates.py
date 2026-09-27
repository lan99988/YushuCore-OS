from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .evidence import EvidenceStore, _parse_stored_datetime, _validate_id
from .models import PersonalRuleCandidate, PersonalRuleStatus, PersonalRuleTarget


_ALLOWED_TRANSITIONS = {
    PersonalRuleStatus.CANDIDATE: {PersonalRuleStatus.ACTIVE, PersonalRuleStatus.REJECTED},
    PersonalRuleStatus.ACTIVE: {PersonalRuleStatus.REVOKED, PersonalRuleStatus.DEGRADED},
    PersonalRuleStatus.DEGRADED: {PersonalRuleStatus.ACTIVE, PersonalRuleStatus.REVOKED},
    PersonalRuleStatus.REJECTED: set(),
    PersonalRuleStatus.REVOKED: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersonalRuleCandidateStore:
    """Append-only candidate snapshots with explicit human review transitions."""

    def __init__(
        self,
        path: str | Path,
        *,
        evidence_store: EvidenceStore,
        authorized_reviewers: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.path.with_name(f"{self.path.stem}.audit.jsonl")
        self.evidence_store = evidence_store
        self._authorized_reviewers = frozenset(item.strip() for item in authorized_reviewers if item.strip())

    def consider(self, hypothesis_id: str) -> PersonalRuleCandidate | None:
        validation = self.evidence_store.validate(hypothesis_id)
        if validation is None:
            return None
        existing = next((item for item in self.list() if item.hypothesis_id == hypothesis_id), None)
        if existing and existing.status in {PersonalRuleStatus.REJECTED, PersonalRuleStatus.REVOKED}:
            return existing
        if existing:
            status = existing.status
            if status is PersonalRuleStatus.ACTIVE and validation.confidence < 0.5:
                status = PersonalRuleStatus.DEGRADED
            candidate = replace(
                existing,
                supporting_evidence=validation.supporting_evidence,
                counterexamples=validation.counterexamples,
                time_range=validation.time_range,
                confidence=validation.confidence,
                status=status,
            )
            self._save(candidate)
            if status is PersonalRuleStatus.DEGRADED and existing.status is not status:
                self._audit(candidate, "rule_degraded", reviewer="", timestamp=_now())
            return candidate
        candidate = PersonalRuleCandidate(
            rule_id=f"RULE-{uuid4().hex}",
            hypothesis_id=validation.hypothesis.hypothesis_id,
            hypothesis=validation.hypothesis.claim,
            suggested_action=validation.hypothesis.suggested_action,
            target=validation.hypothesis.target,
            supporting_evidence=validation.supporting_evidence,
            counterexamples=validation.counterexamples,
            time_range=validation.time_range,
            confidence=validation.confidence,
            scope=validation.hypothesis.scope,
            proposed_by=validation.hypothesis.proposed_by,
            created_at=_now(),
        )
        self._save(candidate)
        self._audit(candidate, "rule_candidate_created", reviewer="", timestamp=candidate.created_at)
        return candidate

    def list(self) -> tuple[PersonalRuleCandidate, ...]:
        latest: dict[str, PersonalRuleCandidate] = {}
        for payload in self._candidate_events():
            candidate = self._deserialize(payload)
            latest[candidate.rule_id] = candidate
        return tuple(latest.values())

    def get(self, rule_id: str) -> PersonalRuleCandidate:
        _validate_id(rule_id, "rule_id")
        candidate = next((item for item in self.list() if item.rule_id == rule_id), None)
        if candidate is None:
            raise KeyError(rule_id)
        return candidate

    def active_rules(
        self,
        *,
        scope: tuple[str, ...] | list[str] | None = None,
        target: str | PersonalRuleTarget | None = None,
    ) -> tuple[PersonalRuleCandidate, ...]:
        scope_supplied = scope is not None
        requested_scope = frozenset(scope or ())
        requested_target = PersonalRuleTarget(target) if target is not None else None
        active = []
        for candidate in self.list():
            if candidate.status is not PersonalRuleStatus.ACTIVE:
                continue
            if scope_supplied and (
                not requested_scope or not set(candidate.scope).issubset(requested_scope)
            ):
                continue
            if requested_target is not None and candidate.target is not requested_target:
                continue
            validation = self.evidence_store.validate(candidate.hypothesis_id)
            if validation is None:
                continue
            # A stale snapshot or missing evidence must never make an active rule usable.
            if (
                candidate.supporting_evidence != validation.supporting_evidence
                or candidate.counterexamples != validation.counterexamples
                or candidate.time_range != validation.time_range
                or candidate.confidence != validation.confidence
                or candidate.scope != validation.hypothesis.scope
                or candidate.target is not validation.hypothesis.target
                or candidate.hypothesis != validation.hypothesis.claim
                or candidate.suggested_action
                != validation.hypothesis.suggested_action
                or candidate.proposed_by != validation.hypothesis.proposed_by
            ):
                continue
            active.append(candidate)
        return tuple(active)

    def activate(self, rule_id: str, *, reviewer: str) -> PersonalRuleCandidate:
        self._authorize(reviewer)
        candidate = self.get(rule_id)
        if reviewer == candidate.proposed_by:
            raise PermissionError("reviewer must be a different authorized human")
        if candidate.status not in {PersonalRuleStatus.CANDIDATE, PersonalRuleStatus.DEGRADED}:
            raise ValueError("rule candidate cannot be activated from its current status")
        refreshed = self.consider(candidate.hypothesis_id)
        if refreshed is None:
            raise ValueError("rule requires validated evidence")
        if refreshed.status not in {PersonalRuleStatus.CANDIDATE, PersonalRuleStatus.DEGRADED}:
            raise ValueError("rule candidate cannot be activated from its current status")
        if refreshed.confidence < 0.5:
            raise ValueError("rule confidence is below the activation threshold")
        return self._transition(
            refreshed,
            PersonalRuleStatus.ACTIVE,
            reviewer=reviewer,
            note="Human approved the personal rule.",
        )

    def reject(self, rule_id: str, *, reviewer: str, reason: str) -> PersonalRuleCandidate:
        self._authorize(reviewer)
        if not reason.strip():
            raise ValueError("reason is required")
        candidate = self.get(rule_id)
        if reviewer == candidate.proposed_by:
            raise PermissionError("reviewer must be a different authorized human")
        return self._transition(candidate, PersonalRuleStatus.REJECTED, reviewer=reviewer, note=reason)

    def revoke(self, rule_id: str, *, reviewer: str, reason: str) -> PersonalRuleCandidate:
        self._authorize(reviewer)
        if not reason.strip():
            raise ValueError("reason is required")
        candidate = self.get(rule_id)
        if reviewer == candidate.proposed_by:
            raise PermissionError("reviewer must be a different authorized human")
        return self._transition(candidate, PersonalRuleStatus.REVOKED, reviewer=reviewer, note=reason)

    def degrade(self, rule_id: str, *, reviewer: str, reason: str) -> PersonalRuleCandidate:
        self._authorize(reviewer)
        if not reason.strip():
            raise ValueError("reason is required")
        candidate = self.get(rule_id)
        if reviewer == candidate.proposed_by:
            raise PermissionError("reviewer must be a different authorized human")
        return self._transition(candidate, PersonalRuleStatus.DEGRADED, reviewer=reviewer, note=reason)

    def audit_events(self) -> list[dict[str, object]]:
        if not self.audit_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _authorize(self, reviewer: str) -> None:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if reviewer not in self._authorized_reviewers:
            raise PermissionError("reviewer is not an authorized human")

    def _transition(
        self,
        candidate: PersonalRuleCandidate,
        status: PersonalRuleStatus,
        *,
        reviewer: str,
        note: str,
    ) -> PersonalRuleCandidate:
        if status not in _ALLOWED_TRANSITIONS[candidate.status]:
            raise ValueError(f"invalid rule status transition: {candidate.status.value} -> {status.value}")
        updated = replace(candidate, status=status, reviewer=reviewer, review_note=note)
        self._save(updated)
        self._audit(updated, f"rule_{status.value}", reviewer=reviewer, timestamp=_now())
        return updated

    def _candidate_events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _deserialize(self, payload: dict[str, object]) -> PersonalRuleCandidate:
        values = dict(payload)
        for name in ("supporting_evidence", "counterexamples", "scope"):
            values[name] = tuple(values.get(name, ()))
        values["time_range"] = tuple(_parse_stored_datetime(value) for value in values["time_range"])
        return PersonalRuleCandidate(**values)

    def _save(self, candidate: PersonalRuleCandidate) -> None:
        payload = asdict(candidate)
        payload["target"] = candidate.target.value
        payload["status"] = candidate.status.value
        payload["time_range"] = [value.isoformat() for value in candidate.time_range]
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _audit(
        self,
        candidate: PersonalRuleCandidate,
        action: str,
        *,
        reviewer: str,
        timestamp: str,
    ) -> None:
        event = {
            "action": action,
            "rule_id": candidate.rule_id,
            "hypothesis_id": candidate.hypothesis_id,
            "reviewer": reviewer,
            "timestamp": timestamp,
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
