from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.sdk import AgentResponse
from agents.skills import skills_for_domain
from agents.project_execution import build_task_proposal


def project_agent_handler(context) -> AgentResponse:
    response = build_summary("project", context, skills=skills_for_domain("project"))
    findings = analyze_context(context, domain_name="project")
    proposals = review_findings(findings, agent_id=context.agent_id, domain_name="project")
    proposals.append(build_task_proposal(context.task, evidence=[node.id for node in context.knowledge]))
    return AgentResponse(
        summary=f"Project Agent: {response.summary}",
        findings=response.findings,
        proposals=proposals,
        next_actions=["Keep project analysis read-only", "Submit project suggestions through Runtime"],
        skills=response.skills,
        reason=response.reason,
        evidence=response.evidence,
        confidence=response.confidence,
    )
