from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime_core.models import AgentDefinition, RuntimeContext


@dataclass(frozen=True)
class AgentResponse:
    summary: str
    findings: list[str]
    proposals: list[dict[str, Any]]
    next_actions: list[str]


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    domain: str
    required_permissions: tuple[str, ...]
    risk_level: str


class AgentSDK:
    def __init__(
        self,
        *,
        agent_id: str,
        domain: str,
        skills: tuple[SkillSpec, ...] = (),
    ) -> None:
        self.agent_id = agent_id
        self.domain = domain
        self.skills = skills

    def response(
        self,
        *,
        summary: str,
        findings: list[str] | None = None,
        proposals: list[dict[str, Any]] | None = None,
        next_actions: list[str] | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            summary=summary,
            findings=list(findings or []),
            proposals=list(proposals or []),
            next_actions=list(next_actions or []),
        )

    def proposal(
        self,
        *,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
        target_path: str = "",
        target_digest: str = "",
    ) -> dict[str, Any]:
        return {
            "agent": self.agent_id,
            "domain": self.domain,
            "target_id": target_id,
            "target_path": target_path,
            "target_digest": target_digest,
            "old": old,
            "new": new,
            "reason": reason,
            "confidence": confidence,
            "risk": risk,
            "status": "draft",
        }

    def submit_proposal(
        self,
        *,
        runtime,
        credential: str,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
    ):
        return runtime.request_update(
            self.agent_id,
            credential=credential,
            target_id=target_id,
            old=old,
            new=new,
            reason=reason,
            confidence=confidence,
            risk=risk,
        )


def make_agent_definition(
    *,
    agent_id: str,
    name: str,
    domain: str,
    autonomy_level: int,
    risk_level: str,
    permissions: tuple[str, ...],
    handler,
    description: str = "",
    model_policy: str = "local_first",
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        name=name,
        domain=domain,
        autonomy_level=autonomy_level,
        risk_level=risk_level,
        permissions=permissions,
        handler=handler,
        description=description,
        model_policy=model_policy,
    )


def context_findings(context: RuntimeContext) -> list[str]:
    findings: list[str] = []
    for node in context.knowledge:
        findings.append(f"{node.id}:{node.title}")
    for node in context.experience:
        findings.append(f"experience:{node.id}")
    for node in context.principles:
        findings.append(f"principle:{node.id}")
    return findings
