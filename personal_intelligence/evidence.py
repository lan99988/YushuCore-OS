from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .models import PersonalRuleTarget


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ISO_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


Clock = Callable[[], datetime]


def _clock_now(clock: Clock) -> datetime:
    current = clock()
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return current.astimezone(timezone.utc)


def _parse_observed_at(value: str | None, *, clock: Clock) -> datetime:
    if value is None:
        return _clock_now(clock)
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _ISO_DATETIME_PATTERN.fullmatch(value)
    ):
        raise ValueError("observed_at must be timezone-aware ISO format")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("observed_at must be timezone-aware ISO format") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware ISO format")
    normalized = parsed.astimezone(timezone.utc)
    if normalized > _clock_now(clock):
        raise ValueError("observed_at cannot be in the future")
    return normalized


def _parse_stored_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not _ISO_DATETIME_PATTERN.fullmatch(value):
        raise ValueError("stored timestamp must be timezone-aware ISO format")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("stored timestamp must be timezone-aware ISO format") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored timestamp must be timezone-aware ISO format")
    return parsed.astimezone(timezone.utc)


def _validate_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a safe identifier")


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    statement: str
    source_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_id(self.observation_id, "observation_id")
        _validate_id(self.source_id, "source_id")
        if not self.statement.strip():
            raise ValueError("statement is required")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observation timestamp must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))


@dataclass(frozen=True)
class RuleHypothesis:
    hypothesis_id: str
    observation_id: str
    claim: str
    scope: tuple[str, ...]
    suggested_action: str
    target: PersonalRuleTarget
    proposed_by: str

    def __post_init__(self) -> None:
        _validate_id(self.hypothesis_id, "hypothesis_id")
        _validate_id(self.observation_id, "observation_id")
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ValueError("claim is required")
        if not isinstance(self.suggested_action, str) or not self.suggested_action.strip():
            raise ValueError("suggested_action is required")
        if not self.scope or any(not isinstance(part, str) or not part.strip() for part in self.scope):
            raise ValueError("scope is required")
        object.__setattr__(self, "target", PersonalRuleTarget(self.target))


@dataclass(frozen=True)
class RuleEvidence:
    evidence_id: str
    hypothesis_id: str
    observation_id: str
    source_id: str
    supports: bool
    summary: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("evidence_id", "hypothesis_id", "observation_id", "source_id"):
            _validate_id(getattr(self, name), name)
        if not isinstance(self.supports, bool):
            raise ValueError("supports must be bool")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("evidence summary is required")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("evidence observed_at must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))


@dataclass(frozen=True)
class EvidenceValidation:
    hypothesis: RuleHypothesis
    supporting_evidence: tuple[str, ...]
    counterexamples: tuple[str, ...]
    time_range: tuple[datetime, datetime]
    confidence: float


class EvidenceStore:
    """Append-only source ledger for observations, hypotheses, and evidence."""

    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def observations(self) -> tuple[ObservationRecord, ...]:
        self._assert_integrity()
        results = []
        for event in self._events():
            if event["kind"] != "observation":
                continue
            value = dict(event["value"])
            value["observed_at"] = _parse_stored_datetime(value["observed_at"])
            results.append(ObservationRecord(**value))
        return tuple(results)

    def hypotheses(self) -> tuple[RuleHypothesis, ...]:
        self._assert_integrity()
        results = []
        for event in self._events():
            if event["kind"] != "hypothesis":
                continue
            value = event["value"]
            value["scope"] = tuple(value["scope"])
            value["target"] = PersonalRuleTarget(value["target"])
            results.append(RuleHypothesis(**value))
        return tuple(results)

    def evidence(self) -> tuple[RuleEvidence, ...]:
        self._assert_integrity()
        results = []
        for event in self._events():
            if event["kind"] != "evidence":
                continue
            value = dict(event["value"])
            value["observed_at"] = _parse_stored_datetime(value["observed_at"])
            results.append(RuleEvidence(**value))
        return tuple(results)

    def evidence_for(self, hypothesis_id: str) -> tuple[RuleEvidence, ...]:
        _validate_id(hypothesis_id, "hypothesis_id")
        return tuple(item for item in self.evidence() if item.hypothesis_id == hypothesis_id)

    def record_observation(
        self,
        *,
        statement: str,
        source_id: str,
        observed_at: str | None = None,
    ) -> ObservationRecord:
        _validate_id(source_id, "source_id")
        if not statement.strip():
            raise ValueError("statement is required")
        if self.has_source_id(source_id):
            raise ValueError("duplicate source_id")
        observation = ObservationRecord(
            observation_id=f"OBS-{uuid4().hex}",
            statement=statement.strip(),
            source_id=source_id,
            observed_at=_parse_observed_at(observed_at, clock=self._clock),
        )
        self._append("observation", observation)
        return observation

    def formulate_hypothesis(
        self,
        *,
        observation_id: str,
        claim: str,
        scope: tuple[str, ...],
        suggested_action: str,
        target: str | PersonalRuleTarget = PersonalRuleTarget.DECISION_GUIDANCE,
        proposed_by: str = "personal_intelligence_engine",
    ) -> RuleHypothesis:
        _validate_id(observation_id, "observation_id")
        if observation_id not in {item.observation_id for item in self.observations()}:
            raise KeyError(observation_id)
        if not claim.strip() or not suggested_action.strip():
            raise ValueError("claim and suggested_action are required")
        normalized_scope = tuple(dict.fromkeys(part.strip() for part in scope if part.strip()))
        if not normalized_scope:
            raise ValueError("scope is required")
        rule_target = PersonalRuleTarget(target)
        existing = self.find_hypothesis(
            claim=claim,
            scope=normalized_scope,
            suggested_action=suggested_action,
            target=rule_target,
        )
        if existing:
            return existing
        hypothesis = RuleHypothesis(
            hypothesis_id=f"HYP-{uuid4().hex}",
            observation_id=observation_id,
            claim=claim.strip(),
            scope=normalized_scope,
            suggested_action=suggested_action.strip(),
            target=rule_target,
            proposed_by=proposed_by.strip() or "personal_intelligence_engine",
        )
        self._append("hypothesis", hypothesis)
        return hypothesis

    def find_hypothesis(
        self,
        *,
        claim: str,
        scope: tuple[str, ...] | list[str],
        suggested_action: str,
        target: str | PersonalRuleTarget = PersonalRuleTarget.DECISION_GUIDANCE,
    ) -> RuleHypothesis | None:
        normalized_scope = tuple(dict.fromkeys(part.strip() for part in scope if part.strip()))
        rule_target = PersonalRuleTarget(target)
        return next(
            (
                item
                for item in self.hypotheses()
                if item.claim == claim.strip()
                and item.scope == normalized_scope
                and item.suggested_action == suggested_action.strip()
                and item.target is rule_target
            ),
            None,
        )

    def has_source_id(self, source_id: str) -> bool:
        _validate_id(source_id, "source_id")
        return any(item.source_id == source_id for item in self.observations())

    def has_evidence_source(self, hypothesis_id: str, source_id: str) -> bool:
        _validate_id(hypothesis_id, "hypothesis_id")
        _validate_id(source_id, "source_id")
        return any(
            item.hypothesis_id == hypothesis_id and item.source_id == source_id
            for item in self.evidence()
        )

    def record_evidence(self, evidence: RuleEvidence) -> RuleEvidence:
        if not isinstance(evidence, RuleEvidence):
            raise TypeError("evidence must be a RuleEvidence record")
        if not isinstance(evidence.supports, bool):
            raise ValueError("supports must be bool")
        for field_name in ("evidence_id", "hypothesis_id", "observation_id", "source_id"):
            _validate_id(getattr(evidence, field_name), field_name)
        known_evidence = {item.evidence_id for item in self.evidence()}
        if evidence.evidence_id in known_evidence:
            raise ValueError("duplicate evidence_id")
        hypothesis_ids = {item.hypothesis_id for item in self.hypotheses()}
        if evidence.hypothesis_id not in hypothesis_ids:
            raise KeyError(evidence.hypothesis_id)
        observation = next(
            (item for item in self.observations() if item.observation_id == evidence.observation_id),
            None,
        )
        if observation is None:
            raise KeyError(evidence.observation_id)
        if (
            evidence.source_id != observation.source_id
            or evidence.observed_at.astimezone(timezone.utc) != observation.observed_at
            or evidence.summary != observation.statement
        ):
            raise ValueError("evidence does not match observation")
        if any(
            item.hypothesis_id == evidence.hypothesis_id and item.source_id == evidence.source_id
            for item in self.evidence()
        ):
            raise ValueError("duplicate evidence source for hypothesis")
        if not evidence.summary.strip():
            raise ValueError("evidence summary is required")
        if (
            not isinstance(evidence.observed_at, datetime)
            or evidence.observed_at.tzinfo is None
            or evidence.observed_at.utcoffset() is None
        ):
            raise ValueError("evidence timestamp must be timezone-aware")
        self._append("evidence", evidence)
        return evidence

    def validate(self, hypothesis_id: str) -> EvidenceValidation | None:
        _validate_id(hypothesis_id, "hypothesis_id")
        self._assert_integrity()
        hypothesis = next((item for item in self.hypotheses() if item.hypothesis_id == hypothesis_id), None)
        if hypothesis is None:
            raise KeyError(hypothesis_id)
        items = self.evidence_for(hypothesis_id)
        supporting = tuple(item.evidence_id for item in items if item.supports)
        counterexamples = tuple(item.evidence_id for item in items if not item.supports)
        # Independent source IDs are enforced on append; one observation cannot validate a rule.
        if len(supporting) < 2:
            return None
        dates = sorted(item.observed_at for item in items)
        confidence = len(supporting) / (len(supporting) + len(counterexamples))
        return EvidenceValidation(
            hypothesis=hypothesis,
            supporting_evidence=supporting,
            counterexamples=counterexamples,
            time_range=(dates[0], dates[-1]),
            confidence=confidence,
        )

    def _assert_integrity(self) -> None:
        """Rebuild ledger relationships on every validation, not from snapshots."""
        observations: dict[str, ObservationRecord] = {}
        sources: dict[str, str] = {}
        hypotheses: dict[str, RuleHypothesis] = {}
        evidence_ids: set[str] = set()
        evidenced_sources: set[str] = set()
        for event in self._events():
            kind = event["kind"]
            value = dict(event["value"])
            if kind == "observation":
                value["observed_at"] = _parse_stored_datetime(value["observed_at"])
                record = ObservationRecord(**value)
                if record.observation_id in observations or record.source_id in sources:
                    raise ValueError("duplicate observation identity or source")
                observations[record.observation_id] = record
                sources[record.source_id] = record.observation_id
            elif kind == "hypothesis":
                value["scope"] = tuple(value["scope"])
                value["target"] = PersonalRuleTarget(value["target"])
                record = RuleHypothesis(**value)
                if record.hypothesis_id in hypotheses:
                    raise ValueError("duplicate hypothesis_id")
                hypotheses[record.hypothesis_id] = record
            else:
                value["observed_at"] = _parse_stored_datetime(value["observed_at"])
                record = RuleEvidence(**value)
                if record.evidence_id in evidence_ids:
                    raise ValueError("duplicate evidence_id")
                evidence_ids.add(record.evidence_id)

        for hypothesis in hypotheses.values():
            if hypothesis.observation_id not in observations:
                raise ValueError("hypothesis refers to an unknown observation")
        for event in self._events():
            if event["kind"] != "evidence":
                continue
            value = dict(event["value"])
            value["observed_at"] = _parse_stored_datetime(value["observed_at"])
            record = RuleEvidence(**value)
            observation = observations.get(record.observation_id)
            if record.hypothesis_id not in hypotheses or observation is None:
                raise ValueError("evidence refers to an unknown hypothesis or observation")
            if record.source_id in evidenced_sources:
                raise ValueError("duplicate evidence source")
            evidenced_sources.add(record.source_id)
            if (
                record.source_id != observation.source_id
                or record.observed_at != observation.observed_at
                or record.summary != observation.statement
            ):
                raise ValueError("evidence does not match authoritative observation")

    def _events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if (
                    not isinstance(event, dict)
                    or set(event) != {"kind", "value"}
                    or event.get("kind") not in {"observation", "hypothesis", "evidence"}
                    or not isinstance(event.get("value"), dict)
                ):
                    raise ValueError("invalid evidence ledger event")
                events.append(event)
        return events

    def _append(self, kind: str, value: object) -> None:
        if hasattr(value, "__dataclass_fields__"):
            payload = asdict(value)
            if isinstance(payload.get("observed_at"), datetime):
                payload["observed_at"] = payload["observed_at"].isoformat()
            if isinstance(value, RuleHypothesis):
                payload["target"] = value.target.value
        else:
            raise TypeError("ledger values must be dataclass records")
        event = {"kind": kind, "value": payload}
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
