from __future__ import annotations

import json
import importlib
import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from experience_layer import ExperienceRequest
from experience_layer.contracts import ExperienceResponse
from experience_layer.service import ExperienceService
from orchestration import FlowName
from runtime_core.events import EventBus


ROOT = Path(__file__).resolve().parents[1]


def _smoke_runner():
    assert importlib.util.find_spec("scripts.flow_smoke_test") is not None, (
        "scripts.flow_smoke_test is required"
    )
    return importlib.import_module("scripts.flow_smoke_test").run_smoke


class FixedFlow:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def run(self, request, intent):
        if self.error is not None:
            raise self.error
        return self.response


def test_experience_service_emits_safe_flow_events_for_blocked_response():
    assert "events" in inspect.signature(ExperienceService).parameters, (
        "ExperienceService must accept an event bus"
    )
    bus = EventBus()
    response = ExperienceResponse(flow=FlowName.CAPTURE, status="blocked")
    service = ExperienceService(
        {FlowName.CAPTURE: FixedFlow(response=response)}, events=bus
    )
    secret_like_text = "credential=DO-NOT-LOG-128d"

    service.handle(
        ExperienceRequest(
            text=secret_like_text,
            correlation_id="corr-flow-events",
            structured_flow=FlowName.CAPTURE,
        )
    )

    history = bus.history
    assert [event["event"] for event in history] == [
        "flow_started",
        "flow_completed",
    ]
    assert all(event["correlation_id"] == "corr-flow-events" for event in history)
    assert all(event["flow"] == "capture" for event in history)
    assert history[-1]["status"] == "blocked"
    assert secret_like_text not in json.dumps(history, ensure_ascii=False)


def test_experience_service_marks_handler_exception_as_flow_failed():
    assert "events" in inspect.signature(ExperienceService).parameters, (
        "ExperienceService must accept an event bus"
    )
    bus = EventBus()
    service = ExperienceService(
        {FlowName.CAPTURE: FixedFlow(error=RuntimeError("private body sentinel"))},
        events=bus,
    )

    with pytest.raises(RuntimeError):
        service.handle(
            ExperienceRequest(
                text="记一件事",
                correlation_id="corr-flow-failed",
                structured_flow=FlowName.CAPTURE,
            )
        )

    assert [event["event"] for event in bus.history] == [
        "flow_started",
        "flow_failed",
    ]
    assert bus.history[-1]["error_type"] == "RuntimeError"
    assert "private body sentinel" not in json.dumps(bus.history, ensure_ascii=False)


def test_event_bus_sanitizes_subscriber_events_and_isolates_telemetry_failures():
    bus = EventBus()
    received = []
    sentinel = "SENSITIVE-EVENT-METADATA-55c2"

    def broken_sink(_event):
        raise OSError("private sink detail")

    bus.subscribe(broken_sink)
    bus.subscribe(received.append)
    bus.publish(
        {
            "event": "flow_failed",
            "flow": "capture",
            "correlation_id": "corr-safe-snapshot",
            "error_type": "RuntimeError",
            "query": sentinel,
            "title": sentinel,
            "result": sentinel,
            "exception": sentinel,
            "reason": sentinel,
        }
    )

    assert received == bus.history
    assert received[0] == {
        "event": "flow_failed",
        "flow": "capture",
        "correlation_id": "corr-safe-snapshot",
        "error_type": "RuntimeError",
    }
    assert sentinel not in json.dumps(received, ensure_ascii=False)
    assert "private sink detail" not in json.dumps(received, ensure_ascii=False)


def test_offline_smoke_covers_six_flows_and_safe_lifecycle_events():
    report = _smoke_runner()()

    assert [item["flow"] for item in report["flows"]] == [
        "capture",
        "plan",
        "today",
        "adjust",
        "review",
        "explore",
    ]
    assert all(item["status"] in {"completed", "partial", "needs_clarification"} for item in report["flows"])
    assert report["ok"] is True
    assert "flow_started" in {event["event"] for event in report["events"]}
    assert "flow_completed" in {event["event"] for event in report["events"]}
    assert {
        "plan_created",
        "policy_allowed",
        "approval_required",
        "plugin_started",
        "plugin_completed",
        "partial_result",
    } <= {event["event"] for event in report["events"]}
    assert report["network_mode"] == "OFF"


def test_flow_smoke_script_runs_as_one_offline_command():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/flow_smoke_test.py",
            "--scenario",
            "normal",
            "--format",
            "json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["network_mode"] == "OFF"


@pytest.mark.parametrize(
    ("scenario", "required_events"),
    [
        ("plugin_unavailable", {"flow_completed"}),
        ("permission_denied", {"policy_blocked"}),
        (
            "partial_failure",
            {"plugin_failed", "partial_result", "rollback_started", "rollback_completed"},
        ),
    ],
)
def test_offline_smoke_simulates_recovery_scenarios(scenario, required_events):
    report = _smoke_runner()(scenario=scenario)

    event_names = {event["event"] for event in report["events"]}
    assert required_events <= event_names
    assert report["scenario"] == scenario
    assert report["ok"] is True
    if scenario == "partial_failure":
        rollback = next(
            event for event in report["events"] if event["event"] == "rollback_completed"
        )
        partial = next(
            event
            for event in report["events"]
            if event["event"] == "partial_result" and event["source"] == "executor"
        )
        assert rollback["status"] == "simulated"
        assert partial["step_count"] == (
            partial["completed_count"]
            + partial["failed_count"]
            + partial["blocked_count"]
        )


def test_offline_smoke_events_never_include_fixture_bodies():
    report = _smoke_runner()(scenario="partial_failure")
    rendered = json.dumps(report["events"], ensure_ascii=False)

    assert "SENSITIVE-SMOKE-BODY" not in rendered
    assert "knowledge body" not in rendered.casefold()
