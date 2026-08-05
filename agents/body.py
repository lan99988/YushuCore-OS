from __future__ import annotations

from agents._shared import build_summary
from agents.sdk import AgentResponse


def body_agent_handler(context) -> AgentResponse:
    response = build_summary("body", context)
    return AgentResponse(
        summary=f"Body Agent: {response.summary}",
        findings=response.findings,
        proposals=[],
        next_actions=["保持身体领域只读分析", "通过 Runtime 提交健康建议"],
    )
