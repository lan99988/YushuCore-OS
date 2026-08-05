from __future__ import annotations

from agents.knowledge_analyzer import KnowledgeFinding
from agents.sdk import AgentSDK


def review_findings(
    findings: list[KnowledgeFinding],
    *,
    agent_id: str = "knowledge_agent",
    domain: str = "knowledge",
) -> list[dict]:
    sdk = AgentSDK(agent_id=agent_id, domain=domain)
    proposals: list[dict] = []
    for finding in findings:
        proposals.append(
            sdk.proposal(
                target_id=finding.node_id,
                target_path=finding.source_path,
                old=finding.summary,
                new=f"{finding.summary}\n\nReview note: keep this change human-approved.",
                reason="Convert finding into a reviewed knowledge proposal.",
                confidence=0.7,
                risk="medium",
            )
        )
    return proposals
