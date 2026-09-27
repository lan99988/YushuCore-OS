from __future__ import annotations

from types import SimpleNamespace

import pytest

from experience_layer.contracts import ExperienceRequest
from experience_layer.presenter import ExperiencePresenter
from orchestration import CapabilityRequest, FlowName, UserIntent


def _intent(flow=FlowName.PLAN):
    return UserIntent(
        flow=flow,
        text="帮我实现英语能力提升目标",
        confidence=0.99,
        evidence=("明确目标",),
        correlation_id="corr-plan-test",
    )


def _request(*, context=None, dry_run=False):
    return ExperienceRequest(
        text="帮我实现英语能力提升目标",
        correlation_id="corr-plan-test",
        structured_flow=FlowName.PLAN,
        context=context or {},
        dry_run=dry_run,
    )


def _planning(plan=None, gaps=()):
    return SimpleNamespace(plan=plan, gaps=tuple(gaps))


def _step(step_id, status="completed", result=None, *, reason_code=None, approval_required=False):
    decision = None
    if reason_code is not None or approval_required:
        decision = SimpleNamespace(
            reason_code=reason_code or "approval_required",
            approval_required=approval_required,
        )
    return SimpleNamespace(
        step_id=step_id,
        status=status,
        result=result,
        error_code=reason_code,
        decision=decision,
    )


class RecordingPlanner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def plan(self, intent, requests, *, assumptions=()):
        self.calls.append((intent, tuple(requests), assumptions))
        return self.results.pop(0)


class RecordingExecutor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, plan, *, agent_id, dry_run):
        self.calls.append((plan, agent_id, dry_run))
        return self.results.pop(0)


def _goal_context():
    return {
        "goal": {
            "goal_id": "goal-english",
            "title": "提升英语能力",
            "success_criteria": ["能完成日常英文沟通"],
        },
        "current_state": {"level": "B1", "weekly_hours": 3},
        "gaps": [
            {
                "gap_id": "gap-listening",
                "title": "听力理解不足",
                "current": "需要字幕辅助",
                "desired": "能理解日常对话",
            }
        ],
        "constraints": ["每周投入不超过五小时"],
        "project_plan": _project_plan_result(),
    }


def _project_plan_result():
    return {
        "project": {"project_id": "project-english", "title": "英语能力提升项目"},
        "milestones": [
            {"milestone_id": "milestone-listening", "title": "建立听力习惯"}
        ],
        "tasks": [
            {
                "task_guid": "task-listening",
                "title": "完成一次英语听力练习",
                "milestone_id": "milestone-listening",
                "deadline": "2026-10-04",
                "movable": True,
                "estimated_minutes": 30,
            }
        ],
        "calendar_proposals": [
            {
                "proposal_id": "calendar-listening",
                "summary": "英语听力练习",
                "start_iso": "2026-09-28T19:00:00+08:00",
                "end_iso": "2026-09-28T19:30:00+08:00",
                "task_id": "task-listening",
            }
        ],
    }


def _legacy_project_proposal():
    return {
        "proposal_type": "project_plan",
        "project_plan": {"progress": 0.0, "next_tasks": []},
        "status": "pending_human_review",
        "executed": False,
        "requires_human_review": True,
    }


def _flow(planner, executor):
    from experience_layer.flows.plan import PlanFlow

    return PlanFlow(planner, executor, agent_id="plan-agent")


def test_plan_builds_distinct_goal_state_gap_project_milestone_task_and_calendar_proposal():
    planner = RecordingPlanner((_planning("plan"),))
    executor = RecordingExecutor(
        (
            SimpleNamespace(
                status="partial",
                steps=(
                    _step("plan-goal-parse", result={"title": "提升英语能力"}),
                    _step("plan-project-proposal", result=_legacy_project_proposal()),
                    _step(
                        "milestone-proposal-milestone-listening",
                        result={"status": "pending_human_review"},
                    ),
                    _step(
                        "task-proposal-task-listening",
                        result={"proposal_type": "task", "status": "pending_human_review"},
                    ),
                    _step(
                        "calendar-proposal-calendar-listening",
                        status="blocked",
                        reason_code="approval_required",
                        approval_required=True,
                    ),
                ),
            ),
        )
    )

    result = _flow(planner, executor).run(_request(context=_goal_context()), _intent())

    assert result.flow is FlowName.PLAN
    assert result.status == "partial"
    goal = next(item for item in result.understood if item.reason_code == "goal_defined")
    state = next(item for item in result.understood if item.reason_code == "current_state_recorded")
    gap = next(item for item in result.suggestions if item.reason_code == "goal_gap_identified")
    project = next(item for item in result.suggestions if item.reason_code == "project_proposed")
    milestone = next(item for item in result.suggestions if item.reason_code == "milestone_proposed")
    task = next(item for item in result.suggestions if item.reason_code == "task_proposed")
    calendar = next(item for item in result.confirmations if item.reason_code == "calendar_proposal_confirmation")

    assert goal.item_id == "goal-english"
    assert state.after == {"level": "B1", "weekly_hours": 3}
    assert gap.item_id == "gap-listening"
    assert project.item_id == "project-english"
    assert milestone.item_id == "milestone-listening"
    assert task.item_id == "task-listening"
    assert task.after["title"] == "完成一次英语听力练习"
    assert task.after["task_guid"] == "task-listening"
    assert task.after["deadline"] == "2026-10-04"
    assert task.after["project_id"] == "project-english"
    assert task.after["milestone_id"] == "milestone-listening"
    assert calendar.requires_confirmation is True
    assert calendar.after["start_iso"] == "2026-09-28T19:00:00+08:00"
    assert len({goal.item_id, project.item_id, task.item_id}) == 3

    requests = planner.calls[0][1]
    assert tuple(item.capability for item in requests) == (
        "goal.parse",
        "project.create_proposal",
        "project.milestone_proposal",
        "task.create_proposal",
        "calendar.create_proposal",
    )
    by_step = {item.step_id: item for item in requests}
    goal_request = by_step["plan-goal-parse"]
    project_request = by_step["plan-project-proposal"]
    milestone_request = by_step["milestone-proposal-milestone-listening"]
    task_request = by_step["task-proposal-task-listening"]
    calendar_request = by_step["calendar-proposal-calendar-listening"]
    assert project_request.payload["goal"] == "提升英语能力"
    assert goal_request.payload["goal"]["title"] == "提升英语能力"
    assert project_request.depends_on == ("plan-goal-parse",)
    assert project_request.payload["task_status"] == {
        "完成一次英语听力练习": "pending"
    }
    assert project_request.payload["progress"] == 0.0
    assert milestone_request.payload["project_proposal_id"] == "project-english"
    assert milestone_request.payload["milestone"]["title"] == "建立听力习惯"
    assert milestone_request.depends_on == ("plan-project-proposal",)
    assert task_request.depends_on == ("milestone-proposal-milestone-listening",)
    assert "帮我实现英语能力提升目标" not in repr(task_request.payload["evidence"])
    assert task_request.payload["evidence"] == [
        "project:project-english",
        "task:task-listening",
    ]
    assert calendar_request.depends_on == ("task-proposal-task-listening",)
    assert len(executor.calls) == 1
    assert executor.calls[0][1:] == ("plan-agent", False)

    rendered = ExperiencePresenter().present(result)
    public_text = repr(rendered)
    assert "project.create_proposal" not in public_text
    assert "project.milestone_proposal" not in public_text
    assert "task.create_proposal" not in public_text
    assert "calendar.create_proposal" not in public_text
    assert all("plugin" not in item.title.casefold() for item in (*result.suggestions, *result.confirmations))


def test_external_commitment_task_proposal_requires_confirmation():
    context = _goal_context()
    project_plan = _project_plan_result()
    project_plan["tasks"][0]["external_commitment"] = True
    context["project_plan"] = project_plan
    planner = RecordingPlanner((_planning("plan"),))
    executor = RecordingExecutor(
        (
            SimpleNamespace(
            status="partial",
            steps=(
                _step("plan-goal-parse", result={"title": "提升英语能力"}),
                _step("plan-project-proposal", result=_legacy_project_proposal()),
                    _step("milestone-proposal-milestone-listening", result={"status": "pending_human_review"}),
                    _step(
                        "task-proposal-task-listening",
                        status="blocked",
                        reason_code="approval_required_external_commitment",
                        approval_required=True,
                    ),
                ),
            ),
        )
    )

    result = _flow(planner, executor).run(_request(context=context), _intent())

    task_confirmation = next(
        item for item in result.confirmations if item.reason_code == "external_commitment_requires_confirmation"
    )
    assert task_confirmation.requires_confirmation is True
    assert task_confirmation.item_id == "task-listening"
    assert not any(item.reason_code == "task_proposed" for item in result.suggestions)


def test_project_planning_gap_fails_closed_without_executor_or_provider_names_in_ui():
    gap = SimpleNamespace(
        step_id="plan-project-proposal",
        capability="project.create_proposal",
        reason_code="provider_not_ready",
        explanation="project adapter not active",
    )
    planner = RecordingPlanner((_planning(None, (gap,)),))
    executor = RecordingExecutor(())

    result = _flow(planner, executor).run(_request(context=_goal_context()), _intent())

    assert result.status == "blocked"
    assert result.understood[0].reason_code == "goal_defined"
    assert result.uncertainties[0].reason_code == "provider_not_ready"
    assert executor.calls == []
    assert "project.create_proposal" not in result.uncertainties[0].title


def test_plan_requires_plan_intent_and_propagates_dry_run_to_all_proposals():
    planner = RecordingPlanner((_planning("plan"),))
    executor = RecordingExecutor(
        (
            SimpleNamespace(
            status="dry_run",
            steps=(
                _step("plan-goal-parse", "planned"),
                _step("plan-project-proposal", "planned", _legacy_project_proposal()),
                    _step("milestone-proposal-milestone-listening", "planned"),
                    _step("task-proposal-task-listening", "planned"),
                    _step("calendar-proposal-calendar-listening", "planned"),
                ),
            ),
        )
    )

    result = _flow(planner, executor).run(
        _request(context=_goal_context(), dry_run=True), _intent()
    )

    assert result.flow is FlowName.PLAN
    assert [call[2] for call in executor.calls] == [True]
    assert any(item.reason_code == "calendar_proposal_confirmation" for item in result.confirmations)
    with pytest.raises(ValueError):
        _flow(planner, executor).run(_request(context=_goal_context()), _intent(FlowName.TODAY))


def test_review_next_cycle_input_is_validated_and_included_in_planning_context():
    context = _goal_context()
    context["review_input"] = {
        "after": {
            "focus": "每周稳定练习听力",
            "period": "2026-Q4",
            "reason": "上周期听力进步有限",
        }
    }
    planner = RecordingPlanner((_planning("plan"),))
    executor = RecordingExecutor(
        (
            SimpleNamespace(
            status="completed",
            steps=(
                _step("plan-goal-parse", result={"title": "提升英语能力"}),
                _step("plan-project-proposal", result=_legacy_project_proposal()),
                    _step("milestone-proposal-milestone-listening"),
                    _step("task-proposal-task-listening"),
                    _step("calendar-proposal-calendar-listening"),
                ),
            ),
        )
    )

    result = _flow(planner, executor).run(_request(context=context), _intent())

    cycle = next(item for item in result.understood if item.reason_code == "next_cycle_context")
    assert cycle.after["focus"] == "每周稳定练习听力"
    assert cycle.after["period"] == "2026-Q4"
    assert result.suggestions[1].after["next_cycle_context"]["focus"] == "每周稳定练习听力"
    assumptions = " ".join(planner.calls[0][2])
    assert "每周稳定练习听力" in assumptions
    assert "2026-Q4" in assumptions


def test_invalid_review_next_cycle_input_requires_clarification():
    context = _goal_context()
    context["review_input"] = {"period": "2026-Q4"}
    planner = RecordingPlanner(())
    executor = RecordingExecutor(())

    result = _flow(planner, executor).run(_request(context=context), _intent())

    assert result.status == "needs_clarification"
    assert any(item.reason_code == "next_cycle_context_invalid" for item in result.uncertainties)
    assert planner.calls == []
    assert executor.calls == []


def test_missing_current_state_or_gap_is_reported_as_uncertainty_not_invented():
    planner = RecordingPlanner((_planning(None, ()),))
    executor = RecordingExecutor(())

    result = _flow(planner, executor).run(
        _request(context={"goal": {"title": "建立稳定运动习惯"}}), _intent()
    )

    assert result.status == "needs_clarification"
    assert {item.reason_code for item in result.uncertainties} >= {
        "current_state_missing",
        "gap_data_missing",
        "project_plan_unavailable",
    }
    state_gap = next(
        item for item in result.uncertainties if item.reason_code == "current_state_missing"
    )
    assert state_gap.before is None and state_gap.after is None
