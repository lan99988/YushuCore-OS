from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.sdk import AgentResponse


def body_agent_handler(context) -> AgentResponse:
    response = build_summary("body", context)
    findings = analyze_context(context, domain_name="body")
    return AgentResponse(
        summary=f"Body Agent: {response.summary}",
        findings=response.findings,
        proposals=review_findings(findings, agent_id=context.agent_id, domain_name="body"),
        next_actions=["Keep body analysis read-only", "Submit health suggestions through Runtime"],
    )
