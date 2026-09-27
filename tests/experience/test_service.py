from __future__ import annotations

from orchestration import FlowName


def _api():
    from experience_layer import (
        ExperienceItem,
        ExperiencePresenter,
        ExperienceRequest,
        ExperienceResponse,
        ExperienceService,
    )

    return (
        ExperienceItem,
        ExperiencePresenter,
        ExperienceRequest,
        ExperienceResponse,
        ExperienceService,
    )


class RecordingFlow:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def run(self, request, intent):
        self.calls.append((request, intent))
        return self.response


def test_service_routes_natural_language_to_one_registered_flow():
    ExperienceItem, _, ExperienceRequest, ExperienceResponse, ExperienceService = _api()
    response = ExperienceResponse(
        flow=FlowName.CAPTURE,
        status="completed",
        understood=(
            ExperienceItem(
                item_id="capture-1",
                title="识别到记录",
                reason_code="capture_understood",
            ),
        ),
    )
    flow = RecordingFlow(response)
    service = ExperienceService({FlowName.CAPTURE: flow})
    request = ExperienceRequest(
        text="记下王明下周考试",
        correlation_id="corr-service-capture",
    )

    result = service.handle(request)

    assert result is response
    assert len(flow.calls) == 1
    assert flow.calls[0][1].flow is FlowName.CAPTURE


def test_service_turns_router_clarification_into_user_facing_uncertainty():
    _, _, ExperienceRequest, _, ExperienceService = _api()
    service = ExperienceService({})

    result = service.handle(
        ExperienceRequest(
            text="这件事怎么办",
            correlation_id="corr-service-clarify",
        )
    )

    assert result.status == "needs_clarification"
    assert result.uncertainties[0].reason_code == "intent_not_recognized"
    assert "plugin" not in result.uncertainties[0].title.casefold()


def test_presenter_hides_plugin_diagnostics_unless_explicitly_requested():
    ExperienceItem, ExperiencePresenter, _, ExperienceResponse, _ = _api()
    response = ExperienceResponse(
        flow=FlowName.TODAY,
        status="completed",
        suggestions=(
            ExperienceItem(
                item_id="suggestion-1",
                title="下午处理深度任务",
                reason_code="protect_energy",
            ),
        ),
        diagnostics=(
            {"plugin_id": "task", "capability": "task.list", "step_id": "tasks"},
        ),
    )
    presenter = ExperiencePresenter()

    public = presenter.present(response)
    diagnostic = presenter.present(response, diagnostic=True)

    assert public["suggestions"][0]["reason_code"] == "protect_energy"
    assert "diagnostics" not in public
    assert "task.list" not in repr(public)
    assert diagnostic["diagnostics"][0]["capability"] == "task.list"


def test_service_rejects_flow_handler_returning_a_different_flow():
    _, _, ExperienceRequest, ExperienceResponse, ExperienceService = _api()
    flow = RecordingFlow(
        ExperienceResponse(flow=FlowName.TODAY, status="completed")
    )
    service = ExperienceService({FlowName.CAPTURE: flow})

    try:
        service.handle(
            ExperienceRequest(
                text="记录一件事",
                correlation_id="corr-service-mismatch",
            )
        )
    except ValueError as exc:
        assert "flow" in str(exc)
    else:
        raise AssertionError("mismatched flow response must be rejected")


def test_experience_public_api_exports_wp5_flows():
    from experience_layer import AdjustFlow, CaptureFlow, TodayFlow

    assert AdjustFlow.__name__ == "AdjustFlow"
    assert CaptureFlow.__name__ == "CaptureFlow"
    assert TodayFlow.__name__ == "TodayFlow"


def test_experience_public_api_exports_all_six_flows():
    from experience_layer import (
        AdjustFlow,
        CaptureFlow,
        ExploreFlow,
        PlanFlow,
        ReviewFlow,
        TodayFlow,
    )

    assert {
        flow.__name__
        for flow in (CaptureFlow, PlanFlow, TodayFlow, AdjustFlow, ReviewFlow, ExploreFlow)
    } == {
        "CaptureFlow",
        "PlanFlow",
        "TodayFlow",
        "AdjustFlow",
        "ReviewFlow",
        "ExploreFlow",
    }
