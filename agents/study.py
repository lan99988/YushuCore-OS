from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.sdk import AgentResponse
from agents.skills import skills_for_domain
from agents.study_planner import build_learning_plan


def study_agent_handler(context) -> AgentResponse:
    response = build_summary("study", context, skills=skills_for_domain("study"))
    findings = analyze_context(context, domain_name="study")
    proposals = review_findings(findings, agent_id=context.agent_id, domain_name="study")
    topics = [node.title for node in context.knowledge]
    if topics:
        proposals.append(build_learning_plan(context.task, topics))
    return AgentResponse(
        summary=f"Study Agent: {response.summary}",
        findings=response.findings,
        proposals=proposals,
        next_actions=["Draft study suggestions", "Request knowledge updates through Runtime"],
        skills=response.skills,
        reason=response.reason,
        evidence=response.evidence,
        confidence=response.confidence,
    )
