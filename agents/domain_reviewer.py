from __future__ import annotations

from agents.domain_analyzer import DomainFinding
from agents.sdk import AgentSDK


def review_findings(
    findings: list[DomainFinding],
    *,
    agent_id: str,
    domain_name: str,
) -> list[dict]:
    sdk = AgentSDK(agent_id=agent_id, domain=domain_name)
    proposals: list[dict] = []
    for finding in findings:
        proposals.append(
            sdk.proposal(
                target_id=finding.node_id,
                target_path=finding.source_path,
                old=finding.summary,
                new=f"{finding.summary}\n\nReview note: keep this change human-approved.",
                reason=f"Convert finding into a reviewed {domain_name} proposal.",
                confidence=0.7,
                risk="medium",
            )
        )
    return proposals
