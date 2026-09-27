from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from runtime_core.events import EventBus

from orchestration import ClarificationRequest, FlowName, IntentRouter, UserIntent

from .contracts import ExperienceItem, ExperienceRequest, ExperienceResponse


class ExperienceService:
    """Route a user request to one user-facing flow without exposing plugins."""

    def __init__(
        self,
        handlers: Mapping[FlowName, Any],
        *,
        router: IntentRouter | None = None,
        events: EventBus | None = None,
    ) -> None:
        if not isinstance(handlers, Mapping):
            raise TypeError("handlers must be a mapping")
        if any(not isinstance(flow, FlowName) for flow in handlers):
            raise TypeError("handler keys must be FlowName values")
        if any(not callable(getattr(handler, "run", None)) for handler in handlers.values()):
            raise TypeError("every flow handler must provide run")
        self._handlers = dict(handlers)
        self._router = router or IntentRouter()
        if events is not None and not isinstance(events, EventBus):
            raise TypeError("events must be an EventBus or None")
        self._events = events

    def handle(self, request: ExperienceRequest) -> ExperienceResponse:
        if not isinstance(request, ExperienceRequest):
            raise TypeError("request must be an ExperienceRequest")
        flow_name = (
            request.structured_flow.value
            if request.structured_flow is not None
            else "unresolved"
        )
        self._publish(
            {
                "event": "flow_started",
                "flow": flow_name,
                "correlation_id": request.correlation_id,
            }
        )
        try:
            routed = self._router.route(
                request.text,
                correlation_id=request.correlation_id,
                structured_flow=request.structured_flow,
            )
            if isinstance(routed, ClarificationRequest):
                response = ExperienceResponse(
                    flow=routed.candidate_flow,
                    status="needs_clarification",
                    uncertainties=(
                        ExperienceItem(
                            item_id="uncertainty-router",
                            title=routed.question,
                            reason_code=routed.reason_code,
                        ),
                    ),
                )
                self._finish_flow(response, request.correlation_id)
                return response
            if not isinstance(routed, UserIntent):
                raise TypeError("router returned an unsupported value")
            flow_name = routed.flow.value
            handler = self._handlers.get(routed.flow)
            if handler is None:
                response = ExperienceResponse(
                    flow=routed.flow,
                    status="unsupported",
                    uncertainties=(
                        ExperienceItem(
                            item_id="uncertainty-flow",
                            title="该逻辑链尚未启用。",
                            reason_code="flow_not_enabled",
                        ),
                    ),
                )
                self._finish_flow(response, request.correlation_id)
                return response
            response = handler.run(request, routed)
            if not isinstance(response, ExperienceResponse):
                raise TypeError("flow handler must return ExperienceResponse")
            if response.flow is not routed.flow:
                raise ValueError("flow handler returned a mismatched flow")
            self._finish_flow(response, request.correlation_id)
            return response
        except Exception as exc:
            self._publish(
                {
                    "event": "flow_failed",
                    "flow": flow_name,
                    "correlation_id": request.correlation_id,
                    "error_type": type(exc).__name__,
                }
            )
            raise

    def _finish_flow(self, response: ExperienceResponse, correlation_id: str) -> None:
        flow_name = response.flow.value if response.flow is not None else "unresolved"
        self._publish(
            {
                "event": "flow_completed",
                "flow": flow_name,
                "correlation_id": correlation_id,
                "status": response.status,
            }
        )

    def _publish(self, event: dict[str, Any]) -> None:
        if self._events is not None:
            self._events.publish(event)
