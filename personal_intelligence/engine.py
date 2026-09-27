from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .cognitive import CognitiveProposalEngine, ReflectionEngine
from .decision_history import DecisionHistoryStore
from .evidence import EvidenceStore, RuleEvidence
from .models import CognitiveProposal, PersonalRuleCandidate, PersonalRuleTarget, SelfModelSnapshot
from .rule_candidates import PersonalRuleCandidateStore
from .self_model import SelfModelAccessPolicy


@dataclass(frozen=True)
class IntelligenceAnalysis:
    observations: tuple[str, ...]
    evidence: tuple[str, ...]
    proposals: tuple[CognitiveProposal, ...]
    actions: tuple[str, ...] = ()


class PersonalIntelligenceEngine:
    """Analysis and proposal service; it has no write or execution capability."""

    maximum_autonomy_level = 2

    def __init__(
        self,
        *,
        evidence_store: EvidenceStore | None = None,
        rule_candidate_store: PersonalRuleCandidateStore | None = None,
        decision_history: DecisionHistoryStore | None = None,
    ) -> None:
        self._reflection = ReflectionEngine()
        self._proposals = CognitiveProposalEngine()
        if evidence_store and rule_candidate_store and rule_candidate_store.evidence_store is not evidence_store:
            raise ValueError("evidence and candidate stores must share the same evidence ledger")
        self.evidence_store = evidence_store or (
            rule_candidate_store.evidence_store if rule_candidate_store else None
        )
        self.rule_candidate_store = rule_candidate_store
        self.decision_history = decision_history
        self._self_model_policy = SelfModelAccessPolicy()

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

    def record_rule_observation(
        self,
        *,
        statement: str,
        source_id: str,
        hypothesis: str,
        scope: tuple[str, ...] | list[str],
        suggested_action: str,
        supports: bool = True,
        target: str | PersonalRuleTarget = PersonalRuleTarget.DECISION_GUIDANCE,
        observed_at: str | None = None,
    ) -> PersonalRuleCandidate | None:
        if self.evidence_store is None or self.rule_candidate_store is None:
            raise RuntimeError("rule evidence and candidate stores are required")
        if not isinstance(supports, bool):
            raise ValueError("supports must be bool")
        if not statement.strip() or not hypothesis.strip() or not suggested_action.strip():
            raise ValueError("statement, hypothesis, and suggested_action are required")
        try:
            rule_target = PersonalRuleTarget(target)
        except ValueError as exc:
            raise ValueError("unsupported rule target") from exc
        if not self._self_model_policy.allowed_rule_target(rule_target.value):
            raise ValueError("unsupported rule target")
        if any(not isinstance(part, str) for part in scope):
            raise ValueError("scope values must be strings")
        normalized_scope = tuple(dict.fromkeys(part.strip() for part in scope if part.strip()))
        if not normalized_scope:
            raise ValueError("scope is required")
        existing_hypothesis = self.evidence_store.find_hypothesis(
            claim=hypothesis,
            scope=normalized_scope,
            suggested_action=suggested_action,
            target=rule_target,
        )
        if existing_hypothesis and self.evidence_store.has_evidence_source(
            existing_hypothesis.hypothesis_id, source_id
        ):
            return self.rule_candidate_store.consider(existing_hypothesis.hypothesis_id)
        if self.evidence_store.has_source_id(source_id):
            raise ValueError("duplicate source_id")
        observation = self.evidence_store.record_observation(
            statement=statement,
            source_id=source_id,
            observed_at=observed_at,
        )
        formulated = self.evidence_store.formulate_hypothesis(
            observation_id=observation.observation_id,
            claim=hypothesis,
            scope=normalized_scope,
            suggested_action=suggested_action,
            target=rule_target,
        )
        self.evidence_store.record_evidence(
            RuleEvidence(
                evidence_id=f"EVID-{uuid4().hex}",
                hypothesis_id=formulated.hypothesis_id,
                observation_id=observation.observation_id,
                source_id=source_id,
                supports=supports,
                summary=observation.statement,
                observed_at=observation.observed_at,
            )
        )
        return self.rule_candidate_store.consider(formulated.hypothesis_id)

    def record_decision(
        self,
        *,
        decision: str,
        context: str,
        options: tuple[str, ...] | list[str],
        chosen_action: str,
        reason: str,
        scope: tuple[str, ...] | list[str],
        evidence: tuple[str, ...] | list[str] = (),
        outcome: str = "",
        reflection: str = "",
        agent_id: str = "",
        reviewer: str = "",
        correlation_id: str = "",
        applied_rule_ids: tuple[str, ...] | list[str] = (),
        rule_target: str | PersonalRuleTarget = PersonalRuleTarget.DECISION_GUIDANCE,
    ):
        if self.decision_history is None:
            raise RuntimeError("decision history store is required")
        normalized_scope = tuple(dict.fromkeys(part.strip() for part in scope if part.strip()))
        if self.rule_candidate_store:
            self.decision_history.bind_rule_store(self.rule_candidate_store)
        return self.decision_history.append(
            decision=decision,
            context=context,
            options=options,
            chosen_action=chosen_action,
            reason=reason,
            evidence=evidence,
            outcome=outcome,
            reflection=reflection,
            agent_id=agent_id,
            reviewer=reviewer,
            correlation_id=correlation_id,
            scope=normalized_scope,
            applied_rule_ids=applied_rule_ids,
            rule_target=rule_target,
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
