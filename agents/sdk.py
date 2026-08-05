from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from runtime_core.models import AgentDefinition, AgentGovernance, AgentRequest, AgentResult, RuntimeContext


@dataclass(frozen=True)
class AgentResponse:
    task_id: str = ""
    agent_id: str = ""
    requester: str = ""
    goal: str = ""
    context: str = ""
    constraints: tuple[str, ...] = ()
    permission: str = ""
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    skills: tuple[dict[str, Any], ...] = ()
    sources: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    reason: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    governance: AgentGovernance | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")



@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    domain: str
    required_permissions: tuple[str, ...]
    risk_level: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "domain": self.domain,
            "required_permissions": list(self.required_permissions),
            "risk_level": self.risk_level,
        }


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
        reason: str = "",
        evidence: list[str] | None = None,
        confidence: float = 0.0,
        governance: AgentGovernance | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            task_id="",
            agent_id=self.agent_id,
            requester="",
            goal="",
            context="",
            constraints=(),
            permission="",
            summary=summary,
            findings=list(findings or []),
            proposals=list(proposals or []),
            next_actions=list(next_actions or []),
            skills=tuple(self.skill_manifest()),
            sources=(),
            actions=(),
            reason=reason,
            evidence=list(evidence or []),
            confidence=confidence,
            governance=governance,
        )

    def request(
        self,
        *,
        task_id: str,
        requester: str,
        goal: str,
        context: str,
        constraints: tuple[str, ...] = (),
        permission: str = "requested",
        network_mode: str = "OFF",
        correlation_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentRequest:
        return AgentRequest(
            task_id=task_id,
            requester=requester,
            agent_id=self.agent_id,
            goal=goal,
            context=context,
            constraints=constraints,
            permission=permission,
            network_mode=network_mode,
            correlation_id=correlation_id,
            metadata=dict(metadata or {}),
        )

    def response_from_request(
        self,
        request: AgentRequest,
        *,
        result: str,
        confidence: float,
        sources: tuple[str, ...] = (),
        proposals: tuple[dict[str, Any], ...] = (),
        actions: tuple[str, ...] = (),
        reason: str = "",
        evidence: list[str] | None = None,
        governance: AgentGovernance | None = None,
        status: str = "draft",
    ) -> AgentResponse:
        return AgentResponse(
            task_id=request.task_id,
            agent_id=request.agent_id,
            requester=request.requester,
            goal=request.goal,
            context=request.context,
            constraints=request.constraints,
            permission=request.permission,
            summary=result,
            findings=[],
            proposals=list(proposals),
            next_actions=list(actions),
            skills=tuple(self.skill_manifest()),
            sources=sources,
            actions=actions,
            reason=reason,
            evidence=list(evidence or []),
            confidence=confidence,
            governance=governance,
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

    def skill_manifest(self) -> list[dict[str, Any]]:
        return [skill.to_dict() for skill in self.skills]

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
