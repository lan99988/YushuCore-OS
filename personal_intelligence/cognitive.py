from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .models import CognitiveProposal, SelfModelLayer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Observation:
    statements: tuple[str, ...]
    evidence: tuple[str, ...]


class ReflectionEngine:
    def observe(self, statements: list[str] | tuple[str, ...], *, source_ids: list[str] | tuple[str, ...] = ()) -> Observation:
        normalized = tuple(statement.strip() for statement in statements if statement.strip())
        if not normalized:
            raise ValueError("at least one observation is required")
        return Observation(normalized, tuple(source_ids))


class CognitiveProposalEngine:
    def propose(
        self,
        observation: Observation,
        *,
        question: str,
        target_layer: str | SelfModelLayer,
        agent_id: str = "personal_intelligence_engine",
        confidence: float = 0.6,
        correlation_id: str = "",
    ) -> CognitiveProposal:
        if not question.strip():
            raise ValueError("question is required")
        layer = SelfModelLayer(target_layer)
        risk = "high" if layer in {SelfModelLayer.IDENTITY, SelfModelLayer.VALUE, SelfModelLayer.PRINCIPLE} else "medium"
        return CognitiveProposal(
            proposal_id=f"CP-{uuid4().hex}",
            agent_id=agent_id,
            observation="; ".join(observation.statements),
            pattern="; ".join(observation.statements),
            question=question.strip(),
            reason="Pattern is an observation requiring Human interpretation.",
            evidence=observation.evidence,
            confidence=confidence,
            risk=risk,
            target_layer=layer,
            correlation_id=correlation_id,
            created_at=_now(),
        )
