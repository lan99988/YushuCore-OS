from __future__ import annotations

from types import SimpleNamespace

from experience_layer import ExperienceRequest
from orchestration import FlowName, UserIntent


def _intent():
    return UserIntent(
        flow=FlowName.REVIEW,
        text="复盘本周",
        confidence=0.98,
        evidence=("复盘",),
        correlation_id="corr-review-flow",
    )


def _request():
    return ExperienceRequest(
        text="复盘本周",
        correlation_id="corr-review-flow",
        structured_flow=FlowName.REVIEW,
        context={"period": "2026-W39"},
    )


class Planner:
    def __init__(self, gaps=()):
        self.gaps = gaps
        self.plan_token = object()
        self.calls = []

    def plan(self, intent, requests, *, assumptions=()):
        self.calls.append((intent, tuple(requests), assumptions))
        return SimpleNamespace(
            plan=None if self.gaps else self.plan_token,
            gaps=self.gaps,
        )


class Executor:
    def __init__(self, steps, status="completed"):
        self.steps = tuple(steps)
        self.status = status
        self.calls = []

    def execute(self, plan, *, agent_id, dry_run):
        self.calls.append((plan, agent_id, dry_run))
        return SimpleNamespace(steps=self.steps, status=self.status)


def _step(step_id, result=None, *, status="completed", error_code=None):
    return SimpleNamespace(
        step_id=step_id,
        result=result,
        status=status,
        error_code=error_code,
        decision=None,
    )


def _flow(planner, executor):
    from experience_layer.flows.review import ReviewFlow

    return ReviewFlow(planner, executor, agent_id="experience_agent")


def test_review_builds_behavior_to_next_cycle_chain_and_keeps_causes_hypothetical():
    planner = Planner()
    executor = Executor(
        (
            _step(
                "review-project",
                {
                    "behaviors": [{"title": "完成 4 次深度工作"}],
                    "results": [{"title": "项目里程碑按时完成"}],
                    "trends": [{"title": "下午完成率下降"}],
                    "problems": [{"title": "两次临时改期"}],
                    "cause_hypotheses": [
                        {
                            "title": "睡眠不足可能影响下午专注",
                            "evidence": ["周三睡眠 5 小时"],
                        }
                    ],
                    "recommendations": [{"title": "深度任务前移"}],
                    "next_cycle": {"focus": "上午深度工作", "period": "2026-W40"},
                },
            ),
            _step(
                "review-learning",
                {
                    "behaviors": [{"title": "学习 5 次"}],
                    "results": [{"title": "完成第一章"}],
                    "trends": [],
                    "problems": [],
                    "cause_hypotheses": [],
                    "recommendations": [{"title": "保持短时复习"}],
                },
            ),
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    reason_codes = [item.reason_code for item in response.understood]
    assert reason_codes == [
        "behavior_observed",
        "behavior_observed",
        "result_observed",
        "result_observed",
        "trend_observed",
        "problem_identified",
        "cause_hypothesis",
    ]
    cause = next(
        item for item in response.understood if item.reason_code == "cause_hypothesis"
    )
    assert cause.title.startswith("原因假设：")
    assert cause.after["evidence_count"] == 1
    assert {item.reason_code for item in response.suggestions} == {
        "review_recommendation",
        "next_cycle_input",
    }
    next_cycle = next(
        item for item in response.suggestions if item.reason_code == "next_cycle_input"
    )
    assert next_cycle.after["period"] == "2026-W40"
    assert response.recorded == ()

    requests = planner.calls[0][1]
    assert [item.capability for item in requests] == [
        "project.context",
        "learning.progress",
    ]


def test_review_partial_source_failure_preserves_available_evidence():
    planner = Planner()
    executor = Executor(
        (
            _step(
                "review-project",
                {"behaviors": [{"title": "完成项目检查"}]},
            ),
            _step(
                "review-learning",
                status="failed",
                error_code="plugin_execution_failed",
            ),
        ),
        status="partial",
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "partial"
    assert response.understood[0].reason_code == "behavior_observed"
    assert response.uncertainties[0].reason_code == "plugin_execution_failed"
    assert "learning.progress" not in response.uncertainties[0].title


def test_review_planning_gap_is_explicit_and_does_not_execute():
    gap = SimpleNamespace(
        step_id="review-project",
        capability="project.context",
        reason_code="provider_not_ready",
    )
    planner = Planner(gaps=(gap,))
    executor = Executor(())

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "blocked"
    assert response.uncertainties[0].reason_code == "provider_not_ready"
    assert executor.calls == []


def test_review_rejects_a_provider_claiming_certain_causation_without_evidence():
    planner = Planner()
    executor = Executor(
        (
            _step(
                "review-project",
                {
                    "causes": [
                        {
                            "title": "睡眠不足必然导致失败",
                            "evidence": [],
                            "confirmed": True,
                        }
                    ]
                },
            ),
            _step("review-learning", {}),
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert not any("必然" in item.title for item in response.understood)
    assert response.uncertainties[0].reason_code == "unsupported_causal_claim"


def test_review_consumes_project_plugin_context_envelope():
    planner = Planner()
    executor = Executor(
        (
            _step(
                "review-project",
                {
                    "project": {"name": "Personal OS"},
                    "context": {
                        "behaviors": [{"title": "完成一次项目检查"}],
                        "results": [{"title": "识别一个风险"}],
                    },
                },
            ),
            _step("review-learning", {}),
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert [item.reason_code for item in response.understood] == [
        "behavior_observed",
        "result_observed",
    ]


def test_review_forwards_an_explicit_project_scope():
    planner = Planner()
    executor = Executor((_step("review-project", {}), _step("review-learning", {})))
    request = ExperienceRequest(
        text="复盘本周项目",
        correlation_id="corr-review-project",
        structured_flow=FlowName.REVIEW,
        context={"period": "2026-W39", "project_id": "personal-os"},
    )

    _flow(planner, executor).run(request, _intent())

    assert planner.calls[0][1][0].payload["project_id"] == "personal-os"


def test_review_translates_learning_progress_metrics_into_evidence():
    planner = Planner()
    executor = Executor(
        (
            _step("review-project", {}),
            _step("review-learning", {"completed": 4, "target": 8}),
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "completed"
    progress = next(
        item for item in response.understood if item.reason_code == "result_observed"
    )
    assert progress.after == {"completed": 4, "target": 8, "ratio": 0.5}


def test_review_does_not_treat_empty_or_unknown_mappings_as_valid_evidence():
    planner = Planner()
    executor = Executor(
        (
            _step("review-project", {}),
            _step("review-learning", {"unexpected": "shape"}),
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "needs_clarification"
    assert response.understood == ()
    assert any(
        item.reason_code == "insufficient_review_evidence"
        for item in response.uncertainties
    )
