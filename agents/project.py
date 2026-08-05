from __future__ import annotations

from agents._shared import build_summary
from agents.sdk import AgentResponse


def project_agent_handler(context) -> AgentResponse:
    response = build_summary("project", context)
    return AgentResponse(
        summary=f"Project Agent: {response.summary}",
        findings=response.findings,
        proposals=[],
        next_actions=["汇总项目状态", "通过 Runtime 提交项目变更请求"],
    )
