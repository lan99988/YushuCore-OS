from __future__ import annotations

from agents.sdk import AgentResponse, AgentSDK, SkillSpec, context_findings


def build_summary(agent_name: str, context, *, skills: tuple[SkillSpec, ...] = ()) -> AgentResponse:
    sdk = AgentSDK(agent_id=context.agent_id, domain=agent_name, skills=skills)
    findings = context_findings(context)
    next_actions = [
        "Keep proposals human-reviewed",
        "Stay read-only in the runtime",
        "Submit changes only through Runtime",
    ]
    if not findings:
        next_actions = ["Continue collecting context", "Stay read-only in the runtime"]
    return sdk.response(
        summary=f"{agent_name} completed context organization",
        findings=findings,
        next_actions=next_actions,
        proposals=[],
        reason=f"Reviewed Runtime-provided {agent_name} context without direct resource access.",
        evidence=[item.split(":", 1)[0] for item in findings if ":" in item],
        confidence=0.7 if findings else 0.4,
    )
