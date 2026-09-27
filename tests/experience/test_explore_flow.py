from __future__ import annotations

from types import SimpleNamespace

from experience_layer import ExperienceRequest
from orchestration import FlowName, UserIntent


def _intent(text="最近为什么总拖延？"):
    return UserIntent(
        flow=FlowName.EXPLORE,
        text=text,
        confidence=0.92,
        evidence=("为什么",),
        correlation_id="corr-explore-flow",
    )


def _request(*, requested_action=False):
    return ExperienceRequest(
        text="最近为什么总拖延？",
        correlation_id="corr-explore-flow",
        structured_flow=FlowName.EXPLORE,
        context={
            "time_range": "2026-09-01/2026-09-27",
            "requested_action": requested_action,
        },
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
    def __init__(self, step):
        self.step = step
        self.calls = []

    def execute(self, plan, *, agent_id, dry_run):
        self.calls.append((plan, agent_id, dry_run))
        return SimpleNamespace(status=self.step.status, steps=(self.step,))


def _step(result=None, *, status="completed", error_code=None):
    return SimpleNamespace(
        step_id="explore-knowledge",
        result=result,
        status=status,
        error_code=error_code,
        decision=None,
    )


def _flow(planner, executor):
    from experience_layer.flows.explore import ExploreFlow

    return ExploreFlow(planner, executor, agent_id="experience_agent")


def test_explore_returns_evidence_time_range_and_confidence_via_knowledge_capability():
    planner = Planner()
    executor = Executor(
        _step(
            {
                "items": [
                    {
                        "title": "下午启动任务的延迟更长",
                        "summary": "过去四周下午任务平均晚开始 35 分钟。",
                        "source": "personal.task_history",
                        "observed_at": "2026-09-26",
                        "confidence": 0.82,
                    }
                ]
            }
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "completed"
    finding = response.understood[0]
    assert finding.reason_code == "evidence_based_finding"
    assert finding.after["evidence"] == "personal.task_history"
    assert finding.after["time_range"] == "2026-09-01/2026-09-27"
    assert finding.after["confidence"] == 0.82
    requests = planner.calls[0][1]
    assert [item.capability for item in requests] == ["knowledge.search"]
    assert requests[0].payload["query"] == "最近为什么总拖延？"


def test_explore_states_when_evidence_is_insufficient():
    planner = Planner()
    executor = Executor(_step({"items": []}))

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "needs_clarification"
    assert response.uncertainties[0].reason_code == "insufficient_evidence"


def test_explore_action_request_is_redirected_to_capture_or_plan_without_action_call():
    planner = Planner()
    executor = Executor(
        _step(
            {
                "items": [
                    {
                        "title": "发现一个模式",
                        "summary": "有初步相关性。",
                        "source": "personal.task_history",
                        "observed_at": "2026-09-26",
                        "confidence": 0.7,
                    }
                ]
            }
        )
    )

    response = _flow(planner, executor).run(
        _request(requested_action=True), _intent()
    )

    assert response.suggestions[0].reason_code == "action_requires_capture_or_plan"
    assert all(
        item.capability == "knowledge.search" for item in planner.calls[0][1]
    )


def test_explore_never_imports_or_calls_gateway_directly():
    import ast
    from pathlib import Path

    import experience_layer.flows.explore as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.startswith("knowledge_system") for name in imported)
    assert "Gateway" not in Path(module.__file__).read_text(encoding="utf-8")


def test_explore_invalid_or_failed_provider_data_fails_closed():
    planner = Planner()
    executor = Executor(
        _step(None, status="failed", error_code="plugin_execution_failed")
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "blocked"
    assert response.uncertainties[0].reason_code == "plugin_execution_failed"
    assert "knowledge.search" not in response.uncertainties[0].title


def test_explore_consumes_the_knowledge_plugin_node_projection():
    planner = Planner()
    executor = Executor(
        _step(
            {
                "nodes": [
                    {
                        "id": "KN-HABIT-1",
                        "title": "下午启动延迟",
                        "content": "过去四周下午任务更晚开始。",
                        "observed_at": "2026-09-26",
                        "confidence": 0.78,
                    }
                ],
                "permission": "approved",
                "denied_count": 0,
                "invalid_count": 0,
            }
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "completed"
    finding = response.understood[0]
    assert finding.after["evidence"] == "KN-HABIT-1"
    assert finding.after["observed_at"] == "2026-09-26"
    assert finding.after["time_range"] == "2026-09-01/2026-09-27"


def test_explore_rejects_nodes_without_time_evidence_for_a_bounded_query():
    planner = Planner()
    executor = Executor(
        _step(
            {
                "nodes": [
                    {
                        "id": "KN-UNDATED-1",
                        "title": "无日期模式",
                        "content": "没有时间证据。",
                        "confidence": 0.8,
                    }
                ],
                "permission": "approved",
                "denied_count": 0,
                "invalid_count": 0,
            }
        )
    )

    response = _flow(planner, executor).run(_request(), _intent())

    assert response.status == "needs_clarification"
    assert response.uncertainties[0].reason_code == "invalid_evidence_data"
