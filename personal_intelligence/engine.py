from __future__ import annotations

from dataclasses import dataclass

from .cognitive import CognitiveProposalEngine, ReflectionEngine
from .models import CognitiveProposal, SelfModelSnapshot


@dataclass(frozen=True)
class IntelligenceAnalysis:
    observations: tuple[str, ...]
    evidence: tuple[str, ...]
    proposals: tuple[CognitiveProposal, ...]
    actions: tuple[str, ...] = ()


class PersonalIntelligenceEngine:
    """Analysis and proposal service; it has no write or execution capability."""

    maximum_autonomy_level = 2

    def __init__(self) -> None:
        self._reflection = ReflectionEngine()
        self._proposals = CognitiveProposalEngine()

    def analyze(
        self,
        snapshot: SelfModelSnapshot,
        *,
        observations: tuple[str, ...] | list[str],
        evidence: tuple[str, ...] | list[str],
        question: str,
        target_layer: str = "preference",
        agent_id: str = "personal_intelligence_engine",
        correlation_id: str = "",
    ) -> IntelligenceAnalysis:
        if snapshot.version < 1:
            raise ValueError("Self Model snapshot version must be positive")
        observation = self._reflection.observe(observations, source_ids=evidence)
        proposal = self._proposals.propose(
            observation,
            question=question,
            target_layer=target_layer,
            agent_id=agent_id,
            correlation_id=correlation_id,
        )
        return IntelligenceAnalysis(
            observations=observation.statements,
            evidence=observation.evidence,
            proposals=(proposal,),
        )

    def understand_knowledge(self, context) -> dict[str, object]:
        return {"status": "analysis_only", "knowledge": tuple(context), "actions": ()}

    def analyze_preferences(self, snapshot: SelfModelSnapshot) -> dict[str, object]:
        return {
            "status": "analysis_only",
            "preferences": snapshot.preferences.preferences,
            "actions": (),
        }

    def analyze_decision_logic(self, snapshot: SelfModelSnapshot) -> dict[str, object]:
        return {
            "status": "analysis_only",
            "decision_model": snapshot.decision,
            "actions": (),
        }

    def predict_behavior(self, snapshot: SelfModelSnapshot) -> dict[str, object]:
        return {
            "status": "analysis_only",
            "behavior_patterns": snapshot.behavior.patterns,
            "confidence": tuple(pattern.confidence for pattern in snapshot.behavior.patterns),
            "actions": (),
        }

    def plan_future(self, snapshot: SelfModelSnapshot) -> dict[str, object]:
        return {
            "status": "proposal_only",
            "goals": snapshot.goals.goals,
            "proposals": (),
            "actions": (),
        }
