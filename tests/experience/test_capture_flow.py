from __future__ import annotations

from types import SimpleNamespace

from orchestration import FlowName, UserIntent


def _request(text="我答应周五前把资料发给李明", *, dry_run=False):
    from experience_layer import ExperienceRequest

    return ExperienceRequest(
        text=text,
        correlation_id="corr-capture-flow",
        dry_run=dry_run,
    )


def _intent(text="我答应周五前把资料发给李明"):
    return UserIntent(
        flow=FlowName.CAPTURE,
        text=text,
        confidence=0.98,
        evidence=("答应",),
        correlation_id="corr-capture-flow",
    )


class RecordingPlanner:
    def __init__(self, *, gaps=()):
        self.calls = []
        self.gaps = gaps
        self.plan_token = object()

    def plan(self, intent, requests, *, assumptions=()):
        self.calls.append((intent, tuple(requests), assumptions))
        return SimpleNamespace(
            plan=None if self.gaps else self.plan_token,
            gaps=self.gaps,
        )


class RecordingExecutor:
    def __init__(self, steps, status="partial"):
        self.steps = tuple(steps)
        self.status = status
        self.calls = []

    def execute(self, plan, *, agent_id, dry_run):
        self.calls.append((plan, agent_id, dry_run))
        return SimpleNamespace(status=self.status, steps=self.steps)


def _step(step_id, status, *, reason_code=None, result=None):
    decision = (
        None
        if reason_code is None
        else SimpleNamespace(reason_code=reason_code, approval_required=True)
    )
    return SimpleNamespace(
        step_id=step_id,
        status=status,
        decision=decision,
        result=result,
        error_code=None if decision is not None else reason_code,
    )


def test_capture_extracts_person_commitment_and_task_without_a_form():
    from experience_layer.flows.capture import CaptureFlow

    planner = RecordingPlanner()
    executor = RecordingExecutor(
        (
            _step("capture-record", "completed", result={"object_id": "info-1"}),
            _step(
                "commitment-task",
                "blocked",
                reason_code="approval_required_external_commitment",
            ),
        )
    )
    flow = CaptureFlow(planner, executor, agent_id="experience_agent")

    response = flow.run(_request(), _intent())

    titles = tuple(item.title for item in response.understood)
    assert any("李明" in title for title in titles)
    assert any("承诺" in title for title in titles)
    assert any("任务" in title for title in titles)
    assert response.recorded[0].reason_code == "information_recorded"
    assert response.confirmations[0].reason_code == "approval_required_external_commitment"
    assert response.confirmations[0].requires_confirmation is True

    requests = planner.calls[0][1]
    assert [item.capability for item in requests] == [
        "information.capture",
        "task.create_proposal",
    ]
    assert requests[1].depends_on == ("capture-record",)
    assert requests[1].payload["affects_commitment"] is True
    assert requests[1].payload["due_at"] == "周五"
    assert all("send" not in item.capability for item in requests)


def test_plain_capture_only_records_information():
    from experience_layer.flows.capture import CaptureFlow

    text = "记下王明下周考试"
    planner = RecordingPlanner()
    executor = RecordingExecutor(
        (_step("capture-record", "completed", result={"object_id": "info-2"}),),
        status="completed",
    )
    flow = CaptureFlow(planner, executor, agent_id="experience_agent")

    response = flow.run(_request(text), _intent(text))

    requests = planner.calls[0][1]
    assert [item.capability for item in requests] == ["information.capture"]
    assert response.status == "completed"
    assert response.confirmations == ()
    assert "新信息" in response.understood[0].title


def test_capture_dry_run_previews_without_claiming_information_was_recorded():
    from experience_layer.flows.capture import CaptureFlow

    planner = RecordingPlanner()
    executor = RecordingExecutor(
        (
            _step("capture-record", "planned"),
            _step("commitment-task", "planned"),
        ),
        status="dry_run",
    )
    flow = CaptureFlow(planner, executor, agent_id="experience_agent")

    response = flow.run(_request(dry_run=True), _intent())

    assert response.status == "completed"
    assert response.recorded == ()
    assert {item.reason_code for item in response.suggestions} == {
        "information_capture_preview",
        "commitment_task_preview",
    }
    assert executor.calls[0][2] is True


def test_capture_surfaces_planning_gaps_without_invoking_executor():
    from experience_layer.flows.capture import CaptureFlow

    gap = SimpleNamespace(
        step_id="capture-record",
        capability="information.capture",
        reason_code="provider_not_ready",
        explanation="private registry detail",
    )
    planner = RecordingPlanner(gaps=(gap,))
    executor = RecordingExecutor(())
    flow = CaptureFlow(planner, executor, agent_id="experience_agent")

    response = flow.run(_request("记下这件事"), _intent("记下这件事"))

    assert response.status == "blocked"
    assert response.uncertainties[0].reason_code == "provider_not_ready"
    assert "private registry detail" not in response.uncertainties[0].title
    assert executor.calls == []


def test_capture_user_facing_items_never_expose_plugin_or_capability_names():
    from experience_layer.flows.capture import CaptureFlow

    planner = RecordingPlanner()
    executor = RecordingExecutor(
        (
            _step("capture-record", "failed", reason_code="plugin_execution_failed"),
            _step("commitment-task", "skipped", reason_code="dependency_not_completed"),
        ),
        status="failed",
    )

    response = CaptureFlow(planner, executor, agent_id="experience_agent").run(
        _request(), _intent()
    )

    public_text = " ".join(
        item.title
        for group in (
            response.understood,
            response.recorded,
            response.suggestions,
            response.confirmations,
            response.uncertainties,
        )
        for item in group
    ).casefold()
    assert "plugin" not in public_text
    assert "information.capture" not in public_text
    assert "task.create_proposal" not in public_text
    assert response.diagnostics
