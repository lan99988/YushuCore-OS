from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from experience_layer.contracts import ExperienceRequest
from orchestration import CapabilityRequest, FlowName, UserIntent


def _intent() -> UserIntent:
    return UserIntent(
        flow=FlowName.TODAY,
        text="安排今天",
        confidence=0.99,
        evidence=("today keyword",),
        correlation_id="corr-today-test",
    )


def _request(*, context=None, dry_run=False) -> ExperienceRequest:
    request_context = dict(context or {})
    request_context.setdefault("target_date", "2026-09-27")
    return ExperienceRequest(
        text="安排今天",
        correlation_id="corr-today-test",
        structured_flow=FlowName.TODAY,
        context=request_context,
        dry_run=dry_run,
    )


def _completed(step_results):
    return SimpleNamespace(status="completed", steps=tuple(step_results))


def _step(step_id, result, *, status="completed", error_code=None):
    return SimpleNamespace(
        step_id=step_id,
        status=status,
        result=result,
        error_code=error_code,
        decision=None,
    )


class RecordingPlanner:
    def __init__(self, result=None):
        self.result = result or SimpleNamespace(plan=object(), gaps=())
        self.calls = []

    def plan(self, intent, requests, *, assumptions=()):
        self.calls.append((intent, tuple(requests), assumptions))
        return self.result


class RecordingExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, plan, *, agent_id, dry_run):
        self.calls.append((plan, agent_id, dry_run))
        return self.result


def _flow(planner, executor, *, rule_provider=None):
    from experience_layer.flows.today import TodayFlow

    return TodayFlow(planner, executor, agent_id="today-agent", rule_provider=rule_provider)


def _fixture_results():
    calendar = {
        "ok": True,
        "type": "calendar",
        "events": [
            {
                "event_id": "meeting-1",
                "summary": "固定项目会议",
                "start": "2026-09-27T09:00:00+08:00",
                "end": "2026-09-27T10:00:00+08:00",
                "fixed_meeting": True,
                "external_commitment": True,
            },
            {
                "event_id": "commitment-1",
                "summary": "交付评审",
                "start": "2026-09-27T16:00:00+08:00",
                "end": "2026-09-27T16:30:00+08:00",
                "external_commitment": True,
                "affects_commitment": True,
            },
        ],
    }
    tasks = [
        {
            "task_guid": "task-due",
            "title": "今天提交预算",
            "priority": "P0",
            "deadline": "2026-09-27T18:00:00+08:00",
            "forced_deadline": True,
            "movable": False,
            "est_time": 60,
            "energy": "high",
        },
        {
            "task_guid": "task-high",
            "title": "准备重要方案",
            "priority": "P1",
            "deadline": "2026-09-29",
            "movable": True,
            "est_time": 90,
        },
        {
            "task_guid": "task-movable",
            "title": "整理项目资料",
            "priority": "P2",
            "deadline": "2026-10-02",
            "movable": True,
            "est_time": 30,
            "start": "2026-09-27T13:00:00+08:00",
            "end": "2026-09-27T13:30:00+08:00",
            "suggested_start": "2026-09-27T11:00:00+08:00",
        },
    ]
    energy = {
        "date": "2026-09-27",
        "body_battery_score": 18,
        "sleep_hours": 5.5,
        "mental_state": "depleted",
        "study_load": "recovery",
    }
    return calendar, tasks, energy


def _success_executor_result():
    calendar, tasks, energy = _fixture_results()
    return _completed(
        (
            _step("today-calendar", calendar),
            _step("today-tasks", tasks),
            _step("today-energy", energy),
        )
    )


def test_today_requests_only_three_read_capabilities_with_offline_inputs():
    planner = RecordingPlanner()
    executor = RecordingExecutor(_success_executor_result())
    snapshot = {"today_energy_context": {"body_battery_score": 18}}

    result = _flow(planner, executor).run(
        _request(context={"target_date": "2026-09-27", "body_snapshot": snapshot}),
        _intent(),
    )

    _, requests, assumptions = planner.calls[0]
    assert tuple(item.capability for item in requests) == (
        "calendar.list_events",
        "task.list",
        "body.current_energy",
    )
    assert tuple(item.step_id for item in requests) == (
        "today-calendar",
        "today-tasks",
        "today-energy",
    )
    assert requests[0].payload == {"target_date": "2026-09-27"}
    assert requests[1].payload["filters"]["target_date"] == "2026-09-27"
    assert requests[2].payload["snapshot"] == snapshot
    assert assumptions
    assert executor.calls == [(planner.result.plan, "today-agent", False)]
    assert result.flow is FlowName.TODAY


def _approved_personal_rule(tmp_path, *, target, scope=("planning",)):
    from personal_intelligence.evidence import EvidenceStore
    from personal_intelligence.engine import PersonalIntelligenceEngine
    from personal_intelligence.rule_candidates import PersonalRuleCandidateStore

    evidence = EvidenceStore(tmp_path / "today-evidence.jsonl")
    candidates = PersonalRuleCandidateStore(
        tmp_path / "today-rules.jsonl",
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
    engine.record_rule_observation(statement="Focus block worked", source_id="today-source-1", **common)
    candidate = engine.record_rule_observation(
        statement="Focus block worked again", source_id="today-source-2", **common
    )
    return candidates, candidates.activate(candidate.rule_id, reviewer="alice")


def _rule_free_today_result():
    return _completed(
        (
            _step("today-calendar", {"events": []}),
            _step("today-tasks", []),
            _step("today-energy", {"body_battery_score": 75, "sleep_hours": 8}),
        )
    )


def test_today_flow_explains_and_stops_returning_revoked_rule(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.TODAY
    )
    flow = _flow(RecordingPlanner(), RecordingExecutor(_rule_free_today_result()), rule_provider=candidates)
    request = _request(context={"rule_scope": ("planning",)})

    first = flow.run(request, _intent())
    explained = [item for item in first.suggestions if item.rule_id == active.rule_id]

    assert len(explained) == 1
    assert active.suggested_action in explained[0].title
    assert explained[0].evidence_refs == active.supporting_evidence
    assert explained[0].confidence == active.confidence

    candidates.revoke(active.rule_id, reviewer="alice", reason="The context changed.")
    second = flow.run(request, _intent())

    assert all(item.rule_id != active.rule_id for item in second.suggestions)


def test_today_flow_does_not_apply_rule_over_protected_schedule(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.TODAY
    )
    flow = _flow(RecordingPlanner(), RecordingExecutor(_success_executor_result()), rule_provider=candidates)

    request = _request(context={"rule_scope": ("caller-controlled",)})
    result = flow.run(request, _intent())
    baseline = _flow(
        RecordingPlanner(), RecordingExecutor(_success_executor_result())
    ).run(request, _intent())

    assert result.hard_constraints
    assert result == baseline
    assert all(item.rule_id != active.rule_id for item in result.suggestions)
    assert all(item.rule_id != active.rule_id for item in result.automatic_adjustments)


def test_today_flow_uses_fixed_planning_scope_not_caller_scope(tmp_path):
    from personal_intelligence.models import PersonalRuleTarget

    candidates, active = _approved_personal_rule(
        tmp_path, target=PersonalRuleTarget.TODAY, scope=("finance",)
    )
    flow = _flow(
        RecordingPlanner(), RecordingExecutor(_rule_free_today_result()),
        rule_provider=candidates,
    )

    result = flow.run(_request(context={"rule_scope": ("finance",)}), _intent())

    assert all(item.rule_id != active.rule_id for item in result.suggestions)


def test_today_classifies_constraints_suggestions_adjustments_and_confirmation():
    planner = RecordingPlanner()
    executor = RecordingExecutor(_success_executor_result())

    result = _flow(planner, executor).run(
        _request(context={"target_date": "2026-09-27"}), _intent()
    )

    assert result.status == "completed"
    hard_titles = " ".join(item.title for item in result.hard_constraints)
    assert "固定项目会议" in hard_titles
    assert "交付评审" in hard_titles
    assert "今天提交预算" in hard_titles
    assert any(item.reason_code == "fixed_calendar_event" for item in result.hard_constraints)
    assert any(item.reason_code == "external_commitment" for item in result.hard_constraints)
    assert any(item.reason_code == "forced_deadline" for item in result.hard_constraints)

    suggestion_titles = " ".join(item.title for item in result.suggestions)
    assert "准备重要方案" in suggestion_titles
    assert any(item.reason_code == "low_energy" for item in result.suggestions)

    assert len(result.automatic_adjustments) == 1
    adjustment = result.automatic_adjustments[0]
    assert adjustment.reason_code == "movable_task_rescheduled_in_draft"
    assert adjustment.before["start"] == "2026-09-27T13:00:00+08:00"
    assert adjustment.after["start"] == "2026-09-27T11:00:00+08:00"
    assert adjustment.before["end"] == "2026-09-27T13:30:00+08:00"
    assert adjustment.after["end"] == "2026-09-27T11:30:00+08:00"
    assert adjustment.requires_confirmation is False

    assert len(result.confirmations) == 1
    assert result.confirmations[0].reason_code == "deadline_energy_conflict"
    assert result.confirmations[0].requires_confirmation is True


def test_missing_provider_returns_explicit_uncertainty_without_execution():
    gap = SimpleNamespace(
        step_id="today-calendar",
        capability="calendar.list_events",
        reason_code="provider_not_ready",
        explanation="calendar adapter offline",
    )
    planner = RecordingPlanner(SimpleNamespace(plan=None, gaps=(gap,)))
    executor = RecordingExecutor(_success_executor_result())

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.status == "blocked"
    assert executor.calls == []
    assert len(result.uncertainties) == 1
    assert result.uncertainties[0].reason_code == "provider_not_ready"
    assert "calendar.list_events" not in result.uncertainties[0].title
    assert result.diagnostics[0]["capability"] == "calendar.list_events"


def test_partial_source_failure_preserves_available_data_and_marks_uncertainty():
    calendar, tasks, _ = _fixture_results()
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        SimpleNamespace(
            status="partial",
            steps=(
                _step("today-calendar", calendar),
                _step("today-tasks", tasks),
                _step("today-energy", None, status="failed", error_code="plugin_execution_failed"),
            ),
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.status == "partial"
    assert any("固定项目会议" in item.title for item in result.hard_constraints)
    assert any("今天提交预算" in item.title for item in result.hard_constraints)
    assert len(result.uncertainties) == 1
    assert result.uncertainties[0].reason_code == "plugin_execution_failed"
    assert "body.current_energy" not in result.uncertainties[0].title
    assert result.diagnostics[-1]["capability"] == "body.current_energy"


def test_low_energy_can_downgrade_only_a_movable_deep_task_in_local_draft():
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": []}),
                _step(
                    "today-tasks",
                    [
                        {
                            "task_guid": "task-deep",
                            "title": "撰写研究方案",
                            "priority": "P2",
                            "work_mode": "deep",
                            "movable": True,
                            "downgrade_allowed": True,
                            "start": "2026-09-27T13:00:00+08:00",
                        },
                        {
                            "task_guid": "task-fixed",
                            "title": "必须原样保留",
                            "work_mode": "deep",
                            "movable": False,
                            "downgrade_allowed": True,
                        },
                    ],
                ),
                _step("today-energy", {"body_battery_score": 18}),
            )
        )
    )

    result = _flow(planner, executor).run(
        _request(context={"target_date": "2026-09-27"}), _intent()
    )

    assert len(result.automatic_adjustments) == 1
    adjustment = result.automatic_adjustments[0]
    assert adjustment.reason_code == "low_energy_deep_work_downgraded"
    assert adjustment.before["work_mode"] == "deep"
    assert adjustment.after["work_mode"] == "light"
    assert adjustment.before["start"] == adjustment.after["start"]
    assert "必须原样保留" not in adjustment.title


def test_malformed_provider_payload_fails_closed_as_uncertainty():
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": "not-a-list"}),
                _step("today-tasks", [{"title": "合法任务"}]),
                _step("today-energy", {"body_battery_score": 50}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.status == "partial"
    assert result.hard_constraints == ()
    assert len(result.uncertainties) == 1
    assert result.uncertainties[0].reason_code == "invalid_calendar_data"


def test_today_output_is_deterministic_and_does_not_mutate_offline_fixture():
    execution = _success_executor_result()
    source = deepcopy(execution.steps)

    first = _flow(RecordingPlanner(), RecordingExecutor(execution)).run(
        _request(context={"target_date": "2026-09-27"}), _intent()
    )
    second = _flow(RecordingPlanner(), RecordingExecutor(execution)).run(
        _request(context={"target_date": "2026-09-27"}), _intent()
    )

    assert execution.steps == source
    assert first == second
    all_user_items = (
        first.hard_constraints
        + first.suggestions
        + first.automatic_adjustments
        + first.confirmations
        + first.uncertainties
    )
    assert all(
        capability not in item.title
        for item in all_user_items
        for capability in ("calendar.", "task.", "body.")
    )


def test_today_rejects_wrong_request_or_intent():
    planner = RecordingPlanner()
    executor = RecordingExecutor(_success_executor_result())
    flow = _flow(planner, executor)

    with pytest.raises(TypeError):
        flow.run({}, _intent())
    wrong_intent = UserIntent(
        flow=FlowName.PLAN,
        text="规划",
        confidence=0.9,
        evidence=("test",),
        correlation_id="corr-today-test",
    )
    with pytest.raises(ValueError):
        flow.run(_request(), wrong_intent)


def test_today_only_treats_fixed_or_external_calendar_and_commitments_as_constraints():
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        _completed(
            (
                _step(
                    "today-calendar",
                    {
                        "events": [
                            {
                                "event_id": "flexible-block",
                                "summary": "可移动专注时段",
                                "start": "2026-09-27T10:00:00+08:00",
                                "end": "2026-09-27T11:00:00+08:00",
                                "movable": True,
                                "fixed_meeting": False,
                                "external_commitment": False,
                            }
                        ]
                    },
                ),
                _step(
                    "today-tasks",
                    [
                        {
                            "task_guid": "external-promise",
                            "title": "把资料发给李明",
                            "deadline": "2026-09-29",
                            "external_commitment": True,
                            "movable": False,
                        }
                    ],
                ),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert len(result.hard_constraints) == 1
    assert result.hard_constraints[0].reason_code == "external_commitment"
    assert "把资料发给李明" in result.hard_constraints[0].title
    assert any(
        item.reason_code == "flexible_calendar_event"
        and "可移动专注时段" in item.title
        for item in result.suggestions
    )


def test_unmarked_legacy_calendar_event_defaults_to_hard_constraint():
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        _completed(
            (
                _step(
                    "today-calendar",
                    {
                        "events": [
                            {
                                "summary": "旧接口返回的会议",
                                "start": "2026-09-27T14:00:00+08:00",
                                "end": "2026-09-27T15:00:00+08:00",
                            }
                        ]
                    },
                ),
                _step("today-tasks", []),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.suggestions == ()
    assert len(result.hard_constraints) == 1
    assert result.hard_constraints[0].reason_code == "fixed_calendar_event"


def test_commitment_or_due_task_is_never_automatically_rescheduled_or_downgraded():
    planner = RecordingPlanner()
    protected_task = {
        "task_guid": "protected-task",
        "title": "答应今天交付的材料",
        "deadline": "2026-09-27T18:00:00+08:00",
        "external_commitment": True,
        "movable": True,
        "work_mode": "deep",
        "downgrade_allowed": True,
        "start": "2026-09-27T13:00:00+08:00",
        "end": "2026-09-27T14:00:00+08:00",
        "suggested_start": "2026-09-27T16:00:00+08:00",
    }
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": []}),
                _step("today-tasks", [protected_task]),
                _step("today-energy", {"body_battery_score": 18}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert any(
        item.reason_code == "external_commitment"
        for item in result.hard_constraints
    )
    assert result.automatic_adjustments == ()


def test_conflicting_suggested_start_is_not_applied_and_requires_confirmation():
    planner = RecordingPlanner()
    movable = {
        "task_guid": "movable-task",
        "title": "可移动任务",
        "movable": True,
        "start": "2026-09-27T13:00:00+08:00",
        "end": "2026-09-27T14:00:00+08:00",
        "suggested_start": "2026-09-27T15:30:00+08:00",
    }
    executor = RecordingExecutor(
        _completed(
            (
                _step(
                    "today-calendar",
                    {
                        "events": [
                            {
                                "summary": "固定会议",
                                "start": "2026-09-27T15:00:00+08:00",
                                "end": "2026-09-27T16:00:00+08:00",
                                "fixed_meeting": True,
                            }
                        ]
                    },
                ),
                _step("today-tasks", [movable]),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.automatic_adjustments == ()
    assert any(
        item.reason_code == "unsafe_suggested_start"
        and item.requires_confirmation is True
        for item in result.confirmations
    )


def test_slash_formatted_due_date_is_a_hard_constraint_and_limits_reschedule():
    planner = RecordingPlanner()
    tasks = [
        {
            "task_guid": "due-today-slash",
            "title": "今天截止",
            "deadline": "2026/09/27",
            "movable": True,
            "start": "2026-09-27T13:00:00+08:00",
            "end": "2026-09-27T14:00:00+08:00",
            "suggested_start": "2026-09-28T09:00:00+08:00",
        },
        {
            "task_guid": "future-slash",
            "title": "明天截止",
            "deadline": "2026/09/28",
            "movable": True,
            "start": "2026-09-27T15:00:00+08:00",
            "end": "2026-09-27T16:00:00+08:00",
            "suggested_start": "2026-09-29T09:00:00+08:00",
        },
    ]
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": []}),
                _step("today-tasks", tasks),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert any(
        item.reason_code == "due_today" and "今天截止" in item.title
        for item in result.hard_constraints
    )
    assert result.automatic_adjustments == ()
    assert any(
        item.reason_code == "unsafe_suggested_start"
        and "明天截止" in item.title
        for item in result.confirmations
    )


def test_suggested_start_conflicting_with_another_task_is_not_applied():
    planner = RecordingPlanner()
    tasks = [
        {
            "task_guid": "moving",
            "title": "准备移动",
            "movable": True,
            "start": "2026-09-27T10:00:00+08:00",
            "end": "2026-09-27T11:00:00+08:00",
            "suggested_start": "2026-09-27T15:30:00+08:00",
        },
        {
            "task_guid": "occupied",
            "title": "已有任务",
            "movable": False,
            "start": "2026-09-27T15:00:00+08:00",
            "end": "2026-09-27T16:30:00+08:00",
        },
    ]
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": []}),
                _step("today-tasks", tasks),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.automatic_adjustments == ()
    assert any(
        item.reason_code == "unsafe_suggested_start"
        for item in result.confirmations
    )


def test_incomplete_task_interval_never_produces_an_automatic_move():
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        _completed(
            (
                _step("today-calendar", {"events": []}),
                _step(
                    "today-tasks",
                    [
                        {
                            "task_guid": "missing-end",
                            "title": "缺少结束时间",
                            "movable": True,
                            "start": "2026-09-27T10:00:00+08:00",
                            "suggested_start": "2026-09-27T15:00:00+08:00",
                        }
                    ],
                ),
                _step("today-energy", {"body_battery_score": 70}),
            )
        )
    )

    result = _flow(planner, executor).run(_request(), _intent())

    assert result.automatic_adjustments == ()
    assert result.confirmations[0].reason_code == "unsafe_suggested_start"
