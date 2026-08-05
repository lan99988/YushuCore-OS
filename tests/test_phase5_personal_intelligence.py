from __future__ import annotations

import pytest


def test_self_model_access_policy_matches_layer_governance():
    from personal_intelligence.models import SelfModelLayer
    from personal_intelligence.self_model import SelfModelAccessPolicy

    policy = SelfModelAccessPolicy()

    assert policy.allowed(SelfModelLayer.EXPERIENCE, "read")
    assert policy.allowed(SelfModelLayer.EXPERIENCE, "analyze")
    assert policy.allowed(SelfModelLayer.EXPERIENCE, "propose")
    assert not policy.allowed(SelfModelLayer.EXPERIENCE, "modify")
    assert policy.allowed(SelfModelLayer.PRINCIPLE, "read")
    assert policy.allowed(SelfModelLayer.PRINCIPLE, "propose")
    assert not policy.allowed(SelfModelLayer.PRINCIPLE, "analyze")
    assert not policy.allowed(SelfModelLayer.PRINCIPLE, "modify")
    assert not policy.allowed(SelfModelLayer.IDENTITY, "read")


def test_self_model_reader_filters_unauthorized_layers_without_filesystem_access():
    from personal_intelligence.models import SelfModelLayer, SelfModelNode
    from personal_intelligence.self_model import SelfModelReader

    reader = SelfModelReader()
    nodes = [
        SelfModelNode("exp-1", SelfModelLayer.EXPERIENCE, "learning reflection", "decision"),
        SelfModelNode("id-1", SelfModelLayer.IDENTITY, "private identity", "human"),
    ]

    visible = reader.read(nodes, operation="read")

    assert [node.node_id for node in visible] == ["exp-1"]
    assert not hasattr(reader, "vault_path")


def test_reflection_creates_cognitive_proposal_without_updating_personal_memory():
    from personal_intelligence.cognitive import CognitiveProposalEngine, ReflectionEngine

    observation = ReflectionEngine().observe(
        ["deep study time declined", "project time increased"],
        source_ids=["decision-1", "decision-2"],
    )
    proposal = CognitiveProposalEngine().propose(
        observation,
        question="是否需要重新评估学习优先级？",
        target_layer="preference",
    )

    assert proposal.status == "pending_human_review"
    assert proposal.target_layer == "preference"
    assert proposal.approved is False
    assert proposal.evidence == ("decision-1", "decision-2")


def test_decision_history_is_append_only(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    store = DecisionHistoryStore(tmp_path / "history.jsonl")
    record = store.append(
        decision="prioritize project delivery",
        context="deadline approaching",
        options=["study", "project"],
        chosen_action="project",
        reason="deadline",
        evidence=["project-1"],
        correlation_id="corr-1",
    )

    assert store.list()[0].decision_id == record.decision_id
    with pytest.raises(PermissionError, match="append-only"):
        store.update(record.decision_id, {"chosen_action": "study"})


def test_personal_model_interface_is_local_only_and_non_training():
    from personal_intelligence.interface import PersonalModelInterface

    interface = PersonalModelInterface()
    descriptor = interface.describe_model()
    route = interface.select_route(sensitivity="level_2", network_mode="OFF")

    assert descriptor.local_only is True
    assert route.provider == "local"
    with pytest.raises(NotImplementedError, match="training"):
        interface.train([])


def test_self_model_gateway_reader_uses_temporary_gateway_grant():
    from knowledge_system.gateway import ContextResponse
    from personal_intelligence.models import SelfModelLayer
    from personal_intelligence.self_model import SelfModelGatewayReader

    class Gateway:
        def get_context_with_access_grant(self, task, **kwargs):
            assert kwargs["resource_path"] == "11_Self_Model"
            assert kwargs["max_sensitivity"] == "level_2"
            return ContextResponse(knowledge=[], experience=[], principles=[])

    result = SelfModelGatewayReader(Gateway(), approved_agents=("study_agent",)).read_for_agent(
        task="reflect on preferences",
        agent_id="study_agent",
        credential="credential",
        resource_path="11_Self_Model",
        max_sensitivity="level_2",
    )

    assert result == ()


def test_self_model_gateway_reader_denies_unapproved_agents():
    from personal_intelligence.self_model import SelfModelGatewayReader

    with pytest.raises(PermissionError, match="approved"):
        SelfModelGatewayReader(object()).read_for_agent(
            task="identity",
            agent_id="body_agent",
            credential="credential",
            resource_path="11_Self_Model",
            max_sensitivity="level_4",
        )


def test_cognitive_proposal_store_requires_human_review_and_audits_transition(tmp_path):
    from personal_intelligence.cognitive import CognitiveProposalEngine, ReflectionEngine
    from personal_intelligence.cognitive_store import CognitiveProposalStore

    observation = ReflectionEngine().observe(["study time declined"], source_ids=["dec-1"])
    proposal = CognitiveProposalEngine().propose(
        observation, question="Re-evaluate study priority?", target_layer="preference", agent_id="study_agent"
    )
    store = CognitiveProposalStore(tmp_path / "proposals")
    store.save(proposal)

    with pytest.raises(PermissionError, match="reviewer"):
        store.approve(proposal.proposal_id, reviewer="study_agent")
    approved = store.approve(proposal.proposal_id, reviewer="human")

    assert approved.status == "approved"
    assert approved.approved is True
    assert any(item["action"] == "cognitive_proposal_approved" for item in store.audit_events())


def test_decision_history_append_writes_non_content_audit_event(tmp_path):
    from personal_intelligence.decision_history import DecisionHistoryStore

    store = DecisionHistoryStore(tmp_path / "history.jsonl")
    record = store.append(
        decision="choose project",
        context="deadline",
        options=["study", "project"],
        chosen_action="project",
        reason="deadline",
        correlation_id="corr-history",
        agent_id="project_agent",
    )

    event = store.audit_events()[0]
    assert event["decision_id"] == record.decision_id
    assert event["correlation_id"] == "corr-history"
    assert "deadline" not in event


def test_self_model_snapshot_contains_all_eight_cognitive_models():
    from personal_intelligence.models import (
        BehaviorModel,
        CapabilityModel,
        DecisionModel,
        GoalModel,
        IdentityModel,
        PreferenceModel,
        SelfModelSnapshot,
        ThinkingModel,
        ValueModel,
    )

    snapshot = SelfModelSnapshot(
        identity=IdentityModel(roles=("engineer",), life_stage="growth", important_domains=("health",), self_description="builder"),
        values=ValueModel(values=()),
        goals=GoalModel(goals=()),
        preferences=PreferenceModel(preferences=()),
        thinking=ThinkingModel(patterns=()),
        decision=DecisionModel(decision_type="general", factors=(), risk="low"),
        behavior=BehaviorModel(patterns=()),
        capabilities=CapabilityModel(capabilities=()),
        version=1,
    )

    assert snapshot.identity.roles == ("engineer",)
    assert snapshot.version == 1


def test_self_model_version_store_requires_approved_human_change(tmp_path):
    from personal_intelligence.models import SelfModelSnapshot
    from personal_intelligence.versioning import SelfModelVersionStore

    store = SelfModelVersionStore(tmp_path / "self_model.jsonl")
    snapshot = SelfModelSnapshot.empty()
    with pytest.raises(PermissionError, match="reviewer"):
        store.record_change(snapshot, snapshot, reason="automatic", reviewer="")
    record = store.record_change(snapshot, snapshot, reason="human confirmed", reviewer="human")

    assert record.version == 1
    assert store.latest().version == 1


def test_life_database_is_only_a_gateway_interface():
    from personal_intelligence.life_database import LifeDatabasePort, LifeDataRequest

    request = LifeDataRequest(scope="health", agent_id="body_agent", sensitivity="level_2")
    with pytest.raises(NotImplementedError, match="reserved"):
        LifeDatabasePort().read(request)


def test_personal_intelligence_engine_returns_analysis_and_proposal_only():
    from personal_intelligence.engine import PersonalIntelligenceEngine
    from personal_intelligence.models import SelfModelSnapshot

    result = PersonalIntelligenceEngine().analyze(
        SelfModelSnapshot.empty(),
        observations=("deep study time declined",),
        evidence=("decision-1",),
        question="Re-evaluate study priority?",
    )

    assert result.proposals[0].status == "pending_human_review"
    assert result.actions == ()
    assert PersonalIntelligenceEngine.maximum_autonomy_level == 2


def test_self_model_layout_requires_human_approval(tmp_path):
    from personal_intelligence.layout import SelfModelLayout

    layout = SelfModelLayout(tmp_path / "vault")
    with pytest.raises(PermissionError, match="Human approval"):
        layout.initialize(human_approved=False)
    created = layout.initialize(human_approved=True)

    assert (tmp_path / "vault/11_Self_Model/identity") in created
    assert (tmp_path / "vault/12_Decision_History/decisions") in created


def test_engine_exposes_five_read_only_intelligence_capabilities():
    from personal_intelligence.engine import PersonalIntelligenceEngine
    from personal_intelligence.models import SelfModelSnapshot

    engine = PersonalIntelligenceEngine()
    snapshot = SelfModelSnapshot.empty()

    assert engine.understand_knowledge(("gateway node",))["status"] == "analysis_only"
    assert engine.analyze_preferences(snapshot)["status"] == "analysis_only"
    assert engine.analyze_decision_logic(snapshot)["status"] == "analysis_only"
    assert engine.predict_behavior(snapshot)["status"] == "analysis_only"
    assert engine.plan_future(snapshot)["status"] == "proposal_only"


def test_goal_execution_port_only_translates_approved_goal_to_proposal():
    from personal_intelligence.execution import GoalExecutionPort

    result = GoalExecutionPort().task_proposal(
        goal_id="GOAL-1", title="Build OS", approved=False
    )

    assert result["status"] == "pending_human_review"
    assert result["execution"] is False
