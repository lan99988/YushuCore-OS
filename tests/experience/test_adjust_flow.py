from __future__ import annotations

from copy import deepcopy

from orchestration import FlowName, UserIntent

from experience_layer.contracts import ExperienceRequest


try:
    from experience_layer.flows.adjust import AdjustFlow
except ImportError:
    AdjustFlow = None


def _run(context: dict, *, rule_provider=None, flow=None):
    assert AdjustFlow is not None, "AdjustFlow is not implemented yet"
    text = "昨晚睡眠不足，帮我调整今天安排"
    correlation_id = "corr-adjust-test"
    request = ExperienceRequest(
        text=text,
        correlation_id=correlation_id,
        structured_flow=FlowName.ADJUST,
        context=context,
    )
    intent = UserIntent(
        flow=FlowName.ADJUST,
        text=text,
        confidence=0.95,
        evidence=("test fixture",),
        correlation_id=correlation_id,
    )
    return (flow or AdjustFlow(rule_provider=rule_provider)).run(request, intent)


def _low_energy() -> dict:
    return {"level": "low", "observed_on": "2026-09-27", "fresh": True}


def _deep_task(**overrides) -> dict:
    item = {
        "item_id": "task-deep-1",
        "title": "准备项目方案",
        "item_type": "task",
        "start": "2026-09-27T15:00:00+08:00",
        "end": "2026-09-27T17:00:00+08:00",
        "work_mode": "deep",
        "movable": True,
        "downgrade_allowed": True,
        "external_calendar": False,
        "external_commitment": False,
        "fixed_meeting": False,
        "forced_deadline": False,
    }
    item.update(overrides)
    return item


def _approved_personal_rule(tmp_path, *, target, scope=("planning",)):
    from personal_intelligence.evidence import EvidenceStore
    from personal_intelligence.engine import PersonalIntelligenceEngine
    from personal_intelligence.rule_candidates import PersonalRuleCandidateStore

    evidence = EvidenceStore(tmp_path / "adjust-evidence.jsonl")
    candidates = PersonalRuleCandidateStore(
        tmp_path / "adjust-rules.jsonl",
        evidence_store=evidence,
        authorized_reviewers=("alice",),
    )
    engine = PersonalIntelligenceEngine(
        evidence_store=evidence, rule_candidate_store=candidates
    )
    common = {
        "hypothesis": "Protect a morning focus block when planning work",
        "scope": scope,
        "suggested_action": "Reserve one morning focus block",
        "target": target,
    }
    engine.record_rule_observation(statement="Focus block worked", source_id="adjust-source-1", **common)
    candidate = engine.record_rule_observation(
        statement="Focus block worked again", source_id="adjust-source-2", **common
    )
    return candidates, candidates.activate(candidate.rule_id, reviewer="alice")


def test_adjust_flow_explains_and_stops_returning_revoked_rule(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget
    from experience_layer.flows.adjust import AdjustFlow

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.ADJUST
    )
    flow = AdjustFlow(rule_provider=candidates)
    context = {"energy": _low_energy(), "items": [], "candidate_slots": [], "rule_scope": ("planning",)}

    first = _run(context, flow=flow)
    explained = [item for item in first.suggestions if item.rule_id == active.rule_id]

    assert len(explained) == 1
    assert active.suggested_action in explained[0].title
    assert explained[0].evidence_refs == active.supporting_evidence

    candidates.revoke(active.rule_id, reviewer="alice", reason="The context changed.")
    second = _run(context, flow=flow)

    assert all(item.rule_id != active.rule_id for item in second.suggestions)


def test_adjust_flow_rejects_today_rule_and_protects_commitments(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget
    from experience_layer.flows.adjust import AdjustFlow

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.ADJUST
    )
    forced = _deep_task(
        item_id="task-forced",
        title="必须按时提交",
        forced_deadline=True,
        deadline="2026-09-27T18:00:00+08:00",
    )
    commitment = _deep_task(
        item_id="task-external",
        title="对外承诺交付",
        external_commitment=True,
    )
    flow = AdjustFlow(rule_provider=candidates)

    context = {
        "energy": _low_energy(),
        "items": [_fixed_meeting(), commitment, forced],
        "candidate_slots": [],
        "rule_scope": ("planning",),
    }
    result = _run(context, flow=flow)
    baseline = _run(context)

    assert result.hard_constraints
    assert any(item.reason_code == "forced_deadline_preserved" for item in result.confirmations)
    assert all(item.rule_id != active.rule_id for item in result.suggestions)
    assert all(item.rule_id != active.rule_id for item in result.automatic_adjustments)
    assert result.hard_constraints == baseline.hard_constraints
    assert result.confirmations == baseline.confirmations
    assert result.automatic_adjustments == baseline.automatic_adjustments


def test_adjust_flow_does_not_use_today_targeted_rule(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget
    from experience_layer.flows.adjust import AdjustFlow

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.TODAY
    )
    result = _run(
        {
            "energy": _low_energy(),
            "items": [],
            "candidate_slots": [],
            "rule_scope": ("planning",),
        },
        flow=AdjustFlow(rule_provider=candidates),
    )

    assert all(item.rule_id != active.rule_id for item in result.suggestions)


def test_adjust_flow_uses_fixed_planning_scope_not_caller_scope(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget
    from experience_layer.flows.adjust import AdjustFlow

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.ADJUST, scope=("finance",)
    )
    flow = AdjustFlow(rule_provider=candidates)

    result = _run(
        {
            "energy": _low_energy(),
            "items": [],
            "candidate_slots": [],
            "rule_scope": ("finance",),
        },
        flow=flow,
    )

    assert all(item.rule_id != active.rule_id for item in result.suggestions)


def _fixed_meeting() -> dict:
    return {
        "item_id": "meeting-1400",
        "title": "14:00 固定会议",
        "item_type": "meeting",
        "start": "2026-09-27T14:00:00+08:00",
        "end": "2026-09-27T15:00:00+08:00",
        "work_mode": None,
        "movable": False,
        "downgrade_allowed": False,
        "external_calendar": True,
        "external_commitment": True,
        "fixed_meeting": True,
        "forced_deadline": False,
    }


def test_low_energy_preserves_fixed_meeting_and_moves_movable_deep_task():
    result = _run(
        {
            "energy": _low_energy(),
            "items": [_fixed_meeting(), _deep_task()],
            "candidate_slots": [
                {
                    "start": "2026-09-28T09:00:00+08:00",
                    "end": "2026-09-28T11:00:00+08:00",
                }
            ],
        }
    )

    assert result.status == "completed"
    assert len(result.hard_constraints) == 1
    meeting = result.hard_constraints[0]
    assert meeting.reason_code == "fixed_commitment_preserved"
    assert meeting.before["start"] == meeting.after["start"] == "2026-09-27T14:00:00+08:00"
    assert meeting.before == meeting.after

    assert result.suggestions == ()
    assert len(result.automatic_adjustments) == 1
    task = result.automatic_adjustments[0]
    assert task.item_id == "adjust-task-deep-1"
    assert task.reason_code == "low_energy_deep_work_moved"
    assert task.before["start"] == "2026-09-27T15:00:00+08:00"
    assert task.after["start"] == "2026-09-28T09:00:00+08:00"
    assert task.before != task.after
    assert task.requires_confirmation is False
    assert result.confirmations == ()


def test_low_energy_downgrades_deep_task_when_no_slot_fits():
    result = _run(
        {
            "energy": _low_energy(),
            "items": [_deep_task()],
            "candidate_slots": [],
        }
    )

    assert result.suggestions == ()
    assert len(result.automatic_adjustments) == 1
    task = result.automatic_adjustments[0]
    assert task.reason_code == "low_energy_deep_work_downgraded"
    assert task.before["work_mode"] == "deep"
    assert task.after["work_mode"] == "light"
    assert task.before["start"] == task.after["start"]
    assert task.requires_confirmation is False


def test_fixed_meeting_and_external_commitment_are_not_replanned():
    result = _run(
        {
            "energy": _low_energy(),
            "items": [_fixed_meeting()],
            "candidate_slots": [
                {
                    "start": "2026-09-28T09:00:00+08:00",
                    "end": "2026-09-28T11:00:00+08:00",
                }
            ],
        }
    )

    assert result.suggestions == ()
    assert result.confirmations == ()
    assert len(result.hard_constraints) == 1
    assert result.hard_constraints[0].reason_code == "fixed_commitment_preserved"
    assert result.hard_constraints[0].before == result.hard_constraints[0].after


def test_forced_deadline_is_preserved_and_requires_user_decision():
    task = _deep_task(
        item_id="task-deadline-1",
        title="今天必须提交",
        forced_deadline=True,
        deadline="2026-09-27T18:00:00+08:00",
    )
    result = _run(
        {
            "energy": _low_energy(),
            "items": [task],
            "candidate_slots": [
                {
                    "start": "2026-09-28T09:00:00+08:00",
                    "end": "2026-09-28T11:00:00+08:00",
                }
            ],
        }
    )

    assert result.suggestions == ()
    assert len(result.confirmations) == 1
    deadline_item = result.confirmations[0]
    assert deadline_item.reason_code == "forced_deadline_preserved"
    assert deadline_item.before == deadline_item.after
    assert deadline_item.requires_confirmation is True


def test_missing_or_stale_energy_requires_clarification_without_changes():
    for energy in (
        None,
        {"level": "low", "observed_on": "2026-09-20", "fresh": False},
    ):
        context = {
            "items": [_deep_task()],
            "candidate_slots": [
                {
                    "start": "2026-09-28T09:00:00+08:00",
                    "end": "2026-09-28T11:00:00+08:00",
                }
            ],
        }
        if energy is not None:
            context["energy"] = energy
        result = _run(context)

        assert result.status == "needs_clarification"
        assert result.suggestions == ()
        assert result.automatic_adjustments == ()
        assert len(result.uncertainties) == 1
        assert result.uncertainties[0].reason_code == "energy_signal_unavailable"


def test_normal_energy_does_not_replan():
    result = _run(
        {
            "energy": {"level": "normal", "observed_on": "2026-09-27", "fresh": True},
            "items": [_fixed_meeting(), _deep_task()],
            "candidate_slots": [
                {
                    "start": "2026-09-28T09:00:00+08:00",
                    "end": "2026-09-28T11:00:00+08:00",
                }
            ],
        }
    )

    assert result.status == "completed"
    assert result.suggestions == ()
    assert result.confirmations == ()
    assert result.understood[0].reason_code == "no_adjustment_needed"


def test_no_slot_and_non_downgradable_task_surfaces_confirmation():
    result = _run(
        {
            "energy": _low_energy(),
            "items": [_deep_task(downgrade_allowed=False)],
            "candidate_slots": [],
        }
    )

    assert result.suggestions == ()
    assert len(result.confirmations) == 1
    item = result.confirmations[0]
    assert item.reason_code == "no_safe_adjustment_available"
    assert item.before == item.after
    assert item.requires_confirmation is True


def test_adjust_flow_is_deterministic_and_has_no_side_effects():
    context = {
        "energy": _low_energy(),
        "items": [_fixed_meeting(), _deep_task()],
        "candidate_slots": [
            {
                "start": "2026-09-28T09:00:00+08:00",
                "end": "2026-09-28T11:00:00+08:00",
            }
        ],
    }
    original = deepcopy(context)

    first = _run(context)
    second = _run(context)

    assert context == original
    assert first == second
    assert first.recorded == ()
    assert len(first.automatic_adjustments) == 1
    assert first.automatic_adjustments[0].before != first.automatic_adjustments[0].after
