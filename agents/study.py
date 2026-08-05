from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.sdk import AgentResponse
from agents.skills import skills_for_domain


def study_agent_handler(context) -> AgentResponse:
    response = build_summary("study", context, skills=skills_for_domain("study"))
    findings = analyze_context(context, domain_name="study")
    return AgentResponse(
        summary=f"Study Agent: {response.summary}",
        findings=response.findings,
        proposals=review_findings(findings, agent_id=context.agent_id, domain_name="study"),
        next_actions=["Draft study suggestions", "Request knowledge updates through Runtime"],
        skills=response.skills,
    )
