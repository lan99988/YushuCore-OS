from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.boundary import phase3_agent_boundary_report
from agents.sdk import AgentResponse


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    passed: bool
    details: str


def evaluate_capability(response: Any) -> EvaluationResult:
    passed = isinstance(response, AgentResponse) and bool(response.summary)
    return EvaluationResult("capability", passed, "response produced" if passed else "no usable response")


def evaluate_explainability(response: Any) -> EvaluationResult:
    passed = isinstance(response, AgentResponse) and bool(response.reason) and bool(response.evidence) and 0 <= response.confidence <= 1
    return EvaluationResult("explainability", passed, "reason/evidence/confidence present" if passed else "explainability incomplete")


def evaluate_response(response: Any) -> EvaluationResult:
    capability = evaluate_capability(response)
    explainability = evaluate_explainability(response)
    return EvaluationResult("capability_and_explainability", capability.passed and explainability.passed, f"{capability.details}; {explainability.details}")


def evaluate_boundary(governance: Any | None = None, requested_resource: str | None = None) -> EvaluationResult:
    report = phase3_agent_boundary_report()
    denied = requested_resource is None or governance is None or requested_resource in governance.cannot_access
    passed = report.is_clean() and denied
    return EvaluationResult("boundary", passed, f"{report.violation_count} violations")
