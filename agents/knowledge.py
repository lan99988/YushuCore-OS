from __future__ import annotations

from agents._shared import build_summary
from agents.sdk import AgentResponse, AgentSDK


def _proposal_body(node) -> str:
    lines = node.body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _candidate_proposals(context) -> list[dict]:
    sdk = AgentSDK(agent_id=context.agent_id, domain="knowledge")
    proposals: list[dict] = []
    for node in context.knowledge:
        old = _proposal_body(node)
        if not old:
            continue
        proposals.append(
            sdk.proposal(
                target_id=node.id,
                target_path=node.path,
                old=old,
                new=f"{old}\n\nReview note: keep this change human-approved.",
                reason="Convert finding into a reviewed knowledge proposal.",
                confidence=0.7,
                risk="medium",
            )
        )
    return proposals


def knowledge_agent_handler(context) -> AgentResponse:
    response = build_summary("knowledge", context)
    return AgentResponse(
        summary=f"Knowledge Agent: {response.summary}",
        findings=response.findings,
        proposals=_candidate_proposals(context),
        next_actions=response.next_actions,
    )
