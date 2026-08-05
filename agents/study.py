from __future__ import annotations

from agents._shared import build_summary
from agents.sdk import AgentResponse


def study_agent_handler(context) -> AgentResponse:
    response = build_summary("study", context)
    return AgentResponse(
        summary=f"Study Agent: {response.summary}",
        findings=response.findings,
        proposals=[],
        next_actions=["输出学习建议草案", "通过 Runtime 申请知识更新"],
    )
