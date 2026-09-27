from __future__ import annotations

import pytest

from orchestration import FlowName


def _api():
    from experience_layer.contracts import (
        ExperienceItem,
        ExperienceRequest,
        ExperienceResponse,
    )

    return ExperienceItem, ExperienceRequest, ExperienceResponse


def test_request_and_item_take_detached_immutable_snapshots():
    ExperienceItem, ExperienceRequest, _ = _api()
    context = {"tasks": [{"id": "t-1", "labels": ["deep"]}]}
    before = {"start": "09:00", "details": {"energy": "high"}}
    request = ExperienceRequest(
        text="今天怎么安排",
        correlation_id="corr-experience-contract",
        structured_flow=FlowName.TODAY,
        context=context,
        dry_run=True,
    )
    item = ExperienceItem(
        item_id="task-t-1",
        title="深度任务",
        reason_code="energy_adjustment",
        before=before,
        after={"start": "16:00"},
    )

    context["tasks"][0]["labels"].append("caller-edit")
    before["details"]["energy"] = "low"

    assert request.context["tasks"][0]["labels"] == ("deep",)
    assert item.before["details"]["energy"] == "high"
    with pytest.raises(TypeError):
        request.context["new"] = "forbidden"
    with pytest.raises(TypeError):
        item.before["details"]["energy"] = "forbidden"


def test_response_requires_items_and_matching_flow_contract():
    ExperienceItem, _, ExperienceResponse = _api()
    understood = ExperienceItem(
        item_id="understood-1",
        title="识别到一项记录",
        reason_code="capture_understood",
    )

    response = ExperienceResponse(
        flow=FlowName.CAPTURE,
        status="completed",
        understood=(understood,),
    )

    assert response.understood == (understood,)
    assert response.confirmations == ()
    with pytest.raises(TypeError):
        ExperienceResponse(
            flow=FlowName.CAPTURE,
            status="completed",
            understood=[understood],
        )
    with pytest.raises(ValueError, match="status"):
        ExperienceResponse(flow=FlowName.CAPTURE, status="mystery")


def test_user_facing_request_executes_safe_internal_work_by_default():
    _, ExperienceRequest, _ = _api()

    request = ExperienceRequest(
        text="记下这件事",
        correlation_id="corr-default-execution",
    )

    assert request.dry_run is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", ""),
        ("correlation_id", "not valid spaces"),
        ("dry_run", 1),
        ("diagnostic", 0),
    ],
)
def test_request_rejects_invalid_boundary_values(field, value):
    _, ExperienceRequest, _ = _api()
    kwargs = {
        "text": "记录一件事",
        "correlation_id": "corr-valid",
        "dry_run": True,
        "diagnostic": False,
    }
    kwargs[field] = value

    with pytest.raises((TypeError, ValueError)):
        ExperienceRequest(**kwargs)
