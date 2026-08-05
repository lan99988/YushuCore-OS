from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.sdk import AgentResponse


def project_agent_handler(context) -> AgentResponse:
    response = build_summary("project", context)
    findings = analyze_context(context, domain_name="project")
    return AgentResponse(
        summary=f"Project Agent: {response.summary}",
        findings=response.findings,
        proposals=review_findings(findings, agent_id=context.agent_id, domain_name="project"),
        next_actions=["Keep project analysis read-only", "Submit project suggestions through Runtime"],
    )
