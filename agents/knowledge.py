from __future__ import annotations

from agents._shared import build_summary
from agents.knowledge_analyzer import analyze_context
from agents.knowledge_reviewer import review_findings
from agents.sdk import AgentResponse
from agents.skills import skills_for_domain


def knowledge_agent_handler(context) -> AgentResponse:
    response = build_summary("knowledge", context, skills=skills_for_domain("knowledge"))
    findings = analyze_context(context)
    return AgentResponse(
        summary=f"Knowledge Agent: {response.summary}",
        findings=response.findings,
        proposals=review_findings(findings, agent_id=context.agent_id),
        next_actions=response.next_actions,
        skills=response.skills,
    )
