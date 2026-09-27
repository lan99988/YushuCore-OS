from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_personal_rule_candidate_api_is_exported_from_the_package_root():
    from personal_intelligence import (
        EvidenceStore,
        PersonalRuleCandidate,
        PersonalRuleCandidateStore,
        PersonalRuleStatus,
        PersonalRuleTarget,
        RuleEvidence,
    )

    assert all(
        value is not None
        for value in (
            EvidenceStore,
            PersonalRuleCandidate,
            PersonalRuleCandidateStore,
            PersonalRuleStatus,
            PersonalRuleTarget,
            RuleEvidence,
        )
    )


def _rule_stack(tmp_path, *, clock=None):
    from personal_intelligence.evidence import EvidenceStore
    from personal_intelligence.engine import PersonalIntelligenceEngine
    from personal_intelligence.rule_candidates import PersonalRuleCandidateStore

    evidence_kwargs = {"clock": clock} if clock else {}
    evidence = EvidenceStore(tmp_path / "evidence.jsonl", **evidence_kwargs)
    candidates = PersonalRuleCandidateStore(
        tmp_path / "rules.jsonl", evidence_store=evidence, authorized_reviewers=("alice",)
    )
    engine = PersonalIntelligenceEngine(evidence_store=evidence, rule_candidate_store=candidates)
    return engine, evidence, candidates


def _observe(engine, source_id: str, *, supports: bool = True, target="decision_guidance"):
    return engine.record_rule_observation(
        statement=f"Observed event from {source_id}",
        source_id=source_id,
        hypothesis="Protect a morning focus block when planning work",
        scope=("planning",),
        suggested_action="Reserve one morning focus block",
        supports=supports,
        observed_at=f"2026-09-{int(source_id[-1]):02d}T09:00:00+00:00",
        target=target,
    )


def test_single_observation_does_not_create_rule(tmp_path):
    engine, evidence, candidates = _rule_stack(tmp_path)

    result = _observe(engine, "event-1")

    assert result is None
    assert len(evidence.observations()) == 1
    assert candidates.list() == ()


def test_repeated_evidence_creates_candidate_not_active_rule(tmp_path):
    engine, _, candidates = _rule_stack(tmp_path)

    assert _observe(engine, "event-1") is None
    candidate = _observe(engine, "event-2")

    assert candidate is not None
    assert candidate.status == "candidate"
    assert candidate.supporting_evidence
    assert candidate.counterexamples == ()
    assert candidate.time_range == (
        datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
        datetime(2026, 9, 2, 9, tzinfo=timezone.utc),
    )
    assert candidate.confidence > 0.5
    assert candidate.scope == ("planning",)
    assert candidates.active_rules() == ()


def test_counterexample_lowers_confidence(tmp_path):
    engine, _, _ = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    original_confidence = candidate.confidence

    revised = _observe(engine, "event-3", supports=False)

    assert revised.confidence < original_confidence
    assert revised.counterexamples


def test_rule_activation_requires_human_approval(tmp_path):
    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")

    import pytest

    with pytest.raises(PermissionError, match="human"):
        candidates.activate(candidate.rule_id, reviewer="personal_intelligence_engine")
    with pytest.raises(PermissionError, match="authorized"):
        candidates.activate(candidate.rule_id, reviewer="someone-claiming-to-be-human")

    active = candidates.activate(candidate.rule_id, reviewer="alice")

    assert active.status == "active"
    assert candidates.active_rules() == (active,)


def test_decision_records_rule_id(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    engine.decision_history = DecisionHistoryStore(tmp_path / "decisions.jsonl")

    decision = engine.record_decision(
        decision="plan today's work",
        context="planning the morning",
        options=("deep work", "meetings"),
        chosen_action="deep work",
        reason="The approved focus-block rule applies.",
        scope=("planning",),
        applied_rule_ids=(active.rule_id,),
    )

    assert decision.rule_ids == (active.rule_id,)
    assert engine.decision_history.list()[0].rule_ids == (active.rule_id,)


def test_revoked_rule_is_not_used(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    candidates.revoke(active.rule_id, reviewer="alice", reason="The context changed.")
    engine.decision_history = DecisionHistoryStore(tmp_path / "decisions.jsonl")

    decision = engine.record_decision(
        decision="adjust today's work",
        context="adjusting the plan",
        options=("deep work", "meetings"),
        chosen_action="meetings",
        reason="The previous rule was revoked.",
        scope=("planning",),
    )

    assert decision.rule_ids == ()
    assert candidates.active_rules() == ()


def test_duplicate_evidence_id_is_rejected_and_cannot_inflate_support(tmp_path):
    import pytest

    engine, evidence, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    first = evidence.evidence_for(candidate.hypothesis_id)[0]

    with pytest.raises(ValueError, match="duplicate evidence_id"):
        evidence.record_evidence(first)

    assert len(candidates.get(candidate.rule_id).supporting_evidence) == 2


def test_scope_mismatch_does_not_record_rule_as_used(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    candidates.activate(candidate.rule_id, reviewer="alice")
    engine.decision_history = DecisionHistoryStore(tmp_path / "decisions.jsonl")

    import pytest

    with pytest.raises(ValueError, match="active|scope|target"):
        engine.record_decision(
            decision="schedule exercise",
            context="planning health activity",
            options=("morning", "evening"),
            chosen_action="evening",
            reason="This rule is for a different scope.",
            scope=("health",),
            applied_rule_ids=(candidate.rule_id,),
        )


def test_protected_self_model_and_system_config_are_not_rule_targets(tmp_path):
    import pytest

    engine, _, _ = _rule_stack(tmp_path)

    for target in ("identity", "value", "principle", "system_config"):
        with pytest.raises(ValueError, match="target"):
            engine.record_rule_observation(
                statement="A planning observation",
                source_id=f"protected-{target}",
                hypothesis="A planning hypothesis",
                scope=("planning",),
                suggested_action="Reserve a focus block",
                target=target,
            )


def test_decision_history_resolves_ids_from_live_rules_not_rule_snapshots(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    history = DecisionHistoryStore(tmp_path / "decisions.jsonl")
    history.bind_rule_store(candidates)

    used = history.append(
        decision="plan today",
        context="morning planning",
        options=("focus", "meetings"),
        chosen_action="focus",
        reason="Use matching guidance.",
        scope=("planning",),
        applied_rule_ids=(active.rule_id,),
    )
    candidates.revoke(active.rule_id, reviewer="alice", reason="The context changed.")
    import pytest

    with pytest.raises(ValueError, match="active|scope|target"):
        history.append(
            decision="adjust today",
            context="updated plan",
            options=("focus", "meetings"),
            chosen_action="meetings",
            reason="The prior rule is revoked.",
            scope=("planning",),
            applied_rule_ids=(active.rule_id,),
        )
    after_revocation = history.append(
        decision="adjust today",
        context="updated plan",
        options=("focus", "meetings"),
        chosen_action="meetings",
        reason="No active rule remains.",
        scope=("planning",),
    )

    assert used.rule_ids == (active.rule_id,)
    assert after_revocation.rule_ids == ()
    assert history.list()[0].rule_ids == (active.rule_id,)


def test_observation_time_requires_aware_iso_and_rejects_future(tmp_path):
    import pytest

    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    engine, evidence, _ = _rule_stack(tmp_path, clock=lambda: now)
    common = {
        "statement": "Observed a focus session",
        "source_id": "time-check-1",
        "hypothesis": "Focus sessions work best in the morning",
        "scope": ("planning",),
        "suggested_action": "Protect a morning focus block",
    }

    for invalid_timestamp in (
        "",
        "2026-09-01T09:00:00",
        "not-a-date",
        "2026-09-01x09:00:00+00:00",
    ):
        with pytest.raises(ValueError, match="timezone-aware ISO"):
            engine.record_rule_observation(**common, observed_at=invalid_timestamp)
    with pytest.raises(ValueError, match="future"):
        engine.record_rule_observation(**common, observed_at="2026-09-28T09:00:00Z")

    assert len(evidence.observations()) == 0


def test_observation_times_normalize_to_utc_and_sort_as_datetimes(tmp_path):
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    engine, _, _ = _rule_stack(tmp_path, clock=lambda: now)
    engine.record_rule_observation(
        statement="First event",
        source_id="event-a",
        hypothesis="Morning focus is more reliable",
        scope=("planning",),
        suggested_action="Reserve focus time",
        observed_at="2026-09-01T11:00:00+02:00",
    )
    candidate = engine.record_rule_observation(
        statement="Second event",
        source_id="event-b",
        hypothesis="Morning focus is more reliable",
        scope=("planning",),
        suggested_action="Reserve focus time",
        observed_at="2026-09-02T09:00:00Z",
    )

    assert candidate.time_range == (
        datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
        datetime(2026, 9, 2, 9, tzinfo=timezone.utc),
    )


def test_evidence_must_match_its_authoritative_observation(tmp_path):
    from dataclasses import replace
    import pytest

    engine, evidence, _ = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    first = evidence.evidence_for(candidate.hypothesis_id)[0]

    for index, changes in enumerate((
        {"source_id": "forged-source"},
        {"observed_at": datetime(2026, 9, 1, 10, tzinfo=timezone.utc)},
        {"summary": "Forged observation content"},
    )):
        with pytest.raises(ValueError, match="does not match observation"):
            evidence.record_evidence(replace(first, evidence_id=f"EVID-unique-test-{index}", **changes))
    with pytest.raises(ValueError, match="supports must be bool"):
        evidence.record_evidence(replace(first, evidence_id="EVID-bad-support", supports=1))


def test_duplicate_source_submission_is_idempotent_without_orphan_observation(tmp_path):
    import pytest

    engine, evidence, _ = _rule_stack(tmp_path)

    _observe(engine, "event-1")
    before = len(evidence.observations())
    result = _observe(engine, "event-1")

    assert result is None
    assert len(evidence.observations()) == before
    with pytest.raises(ValueError, match="duplicate source_id"):
        engine.record_rule_observation(
            statement="Reusing an event for another claim",
            source_id="event-1",
            hypothesis="A different hypothesis",
            scope=("planning",),
            suggested_action="Choose another action",
        )
    assert len(evidence.observations()) == before


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("source_id", "forged-source"),
        ("summary", "Forged but valid event summary"),
        ("observed_at", "2026-09-01T11:00:00+00:00"),
        ("hypothesis_id", "HYP-not-the-linked-hypothesis"),
    ),
)
def test_semantically_tampered_evidence_ledger_fails_closed(tmp_path, field, replacement):
    import json
    import pytest
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, evidence, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    events = [json.loads(line) for line in evidence.path.read_text(encoding="utf-8").splitlines()]
    target = next(
        event for event in events
        if event["kind"] == "evidence" and event["value"]["evidence_id"] == active.supporting_evidence[0]
    )
    target["value"][field] = replacement
    evidence.path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises((ValueError, KeyError)):
        evidence.evidence()
    with pytest.raises((ValueError, KeyError)):
        candidates.active_rules(scope=("planning",), target="decision_guidance")

    history = DecisionHistoryStore(tmp_path / "decisions.jsonl")
    history.bind_rule_store(candidates)
    with pytest.raises((ValueError, KeyError)):
        history.append(
            decision="plan today",
            context="morning planning",
            options=("focus", "meetings"),
            chosen_action="focus",
            reason="Do not trust semantically corrupted evidence.",
            scope=("planning",),
            applied_rule_ids=(active.rule_id,),
        )

    assert history.list() == ()


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("claim", "Tampered hypothesis text"),
        ("suggested_action", "Tampered action"),
        ("proposed_by", "tampered-agent"),
    ),
)
def test_tampered_hypothesis_cannot_keep_a_snapshot_rule_active(
    tmp_path, field, replacement
):
    import json

    engine, evidence, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    events = [
        json.loads(line)
        for line in evidence.path.read_text(encoding="utf-8").splitlines()
    ]
    hypothesis = next(
        event
        for event in events
        if event["kind"] == "hypothesis"
        and event["value"]["hypothesis_id"] == active.hypothesis_id
    )
    hypothesis["value"][field] = replacement
    evidence.path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    assert candidates.active_rules(
        scope=("planning",), target="decision_guidance"
    ) == ()


def test_today_rule_cannot_be_used_for_adjust_or_other_targets(tmp_path):
    import pytest
    from personal_intelligence.models import PersonalRuleTarget

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1", target=PersonalRuleTarget.TODAY)
    candidate = _observe(engine, "event-2", target=PersonalRuleTarget.TODAY)
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine.decision_history = DecisionHistoryStore(tmp_path / "decisions.jsonl")
    common = {
        "decision": "schedule morning work",
        "context": "planning",
        "options": ("focus", "meetings"),
        "chosen_action": "focus",
        "reason": "A target-specific rule was selected.",
        "scope": ("planning",),
        "applied_rule_ids": (active.rule_id,),
    }

    with pytest.raises(ValueError, match="target"):
        engine.record_decision(**common, rule_target=PersonalRuleTarget.ADJUST)
    used = engine.record_decision(**common, rule_target=PersonalRuleTarget.TODAY)
    assert used.rule_ids == (active.rule_id,)


def test_old_decision_history_jsonl_defaults_missing_rule_fields(tmp_path):
    import json
    from personal_intelligence.decision_history import DecisionHistoryStore

    path = tmp_path / "legacy-decisions.jsonl"
    path.write_text(
        json.dumps(
            {
                "decision_id": "DEC-legacy",
                "decision": "choose study",
                "context": "evening",
                "options": ["study", "rest"],
                "chosen_action": "study",
                "reason": "planned",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    record = DecisionHistoryStore(path).list()[0]

    assert record.rule_ids == ()
    assert record.scope == ()


def test_active_rule_is_not_recorded_without_explicit_applied_id(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    candidates.activate(candidate.rule_id, reviewer="alice")
    engine.decision_history = DecisionHistoryStore(tmp_path / "decisions.jsonl")

    decision = engine.record_decision(
        decision="choose work block",
        context="morning",
        options=("focus", "meetings"),
        chosen_action="focus",
        reason="No rule was explicitly consumed.",
        scope=("planning",),
    )

    assert decision.rule_ids == ()


def test_history_rejects_unknown_applied_rule_id(tmp_path):
    import pytest
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    history = DecisionHistoryStore(tmp_path / "decisions.jsonl")
    history.bind_rule_store(candidates)

    with pytest.raises(ValueError, match="active|unknown|scope|target"):
        history.append(
            decision="choose work block",
            context="morning",
            options=("focus", "meetings"),
            chosen_action="focus",
            reason="Unknown rule IDs must not be accepted.",
            scope=("planning",),
            applied_rule_ids=("RULE-00000000000000000000000000000000",),
        )


def test_history_rejects_applied_rule_without_decision_scope(tmp_path):
    import pytest
    from personal_intelligence.decision_history import DecisionHistoryStore

    engine, _, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    active = candidates.activate(candidate.rule_id, reviewer="alice")
    history = DecisionHistoryStore(tmp_path / "decisions.jsonl")
    history.bind_rule_store(candidates)

    with pytest.raises(ValueError, match="active|scope|target"):
        history.append(
            decision="choose work block",
            context="morning",
            options=("focus", "meetings"),
            chosen_action="focus",
            reason="An applied rule needs a matching scope.",
            applied_rule_ids=(active.rule_id,),
        )


def test_corrupt_evidence_ledger_fails_closed_for_active_rules(tmp_path):
    import json
    import pytest

    engine, evidence, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    candidates.activate(candidate.rule_id, reviewer="alice")
    evidence.path.write_text("{broken json\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        candidates.active_rules(scope=("planning",))


def test_malformed_evidence_event_fails_closed_for_active_rules(tmp_path):
    import json
    import pytest

    engine, evidence, candidates = _rule_stack(tmp_path)
    _observe(engine, "event-1")
    candidate = _observe(engine, "event-2")
    candidates.activate(candidate.rule_id, reviewer="alice")
    with evidence.path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": "unknown", "value": {}}) + "\n")

    with pytest.raises(ValueError, match="invalid evidence ledger event"):
        candidates.active_rules(scope=("planning",))
