from __future__ import annotations

from agents.sdk import AgentResponse, AgentSDK, SkillSpec, context_findings


def build_summary(agent_name: str, context) -> AgentResponse:
    sdk = AgentSDK(agent_id=context.agent_id, domain=agent_name)
    findings = context_findings(context)
    next_actions = [
        "整理提案",
        "保持只读执行",
        "通过 Runtime 提交变更请求",
    ]
    if not findings:
        next_actions = ["继续收集上下文", "保持只读执行"]
    return sdk.response(
        summary=f"{agent_name} 已完成上下文整理",
        findings=findings,
        next_actions=next_actions,
        proposals=[],
    )
