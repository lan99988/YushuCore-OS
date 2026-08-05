from __future__ import annotations

from agents._shared import build_summary
from agents.domain_analyzer import analyze_context
from agents.domain_reviewer import review_findings
from agents.body_advisor import assess_body_snapshot
from agents.sdk import AgentResponse
from agents.skills import skills_for_domain


def body_agent_handler(context) -> AgentResponse:
    response = build_summary("body", context, skills=skills_for_domain("body"))
    findings = analyze_context(context, domain_name="body")
    proposals = review_findings(findings, agent_id=context.agent_id, domain_name="body")
    if context.tools.has("body_os.read_snapshot"):
        snapshot = context.tools.call("body_os.read_snapshot")
        proposals.append(assess_body_snapshot(snapshot))
    return AgentResponse(
        summary=f"Body Agent: {response.summary}",
        findings=response.findings,
        proposals=proposals,
        next_actions=["Keep body analysis read-only", "Submit health suggestions through Runtime"],
        skills=response.skills,
        reason=response.reason,
        evidence=response.evidence,
        confidence=response.confidence,
    )
