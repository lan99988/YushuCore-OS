from __future__ import annotations

from agents._shared import build_summary
from agents.sdk import AgentResponse


def knowledge_agent_handler(context) -> AgentResponse:
    response = build_summary("knowledge", context)
    return AgentResponse(
        summary=f"Knowledge Agent: {response.summary}",
        findings=response.findings,
        proposals=[
            {
                "target_id": "knowledge_inbox",
                "status": "draft",
                "reason": "整理知识候选并形成 Proposal",
            }
        ],
        next_actions=response.next_actions,
    )
