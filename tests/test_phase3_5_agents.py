from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_agent_response_contains_explainability_and_governance_fields():
    from agents.sdk import AgentGovernance, AgentSDK

    governance = AgentGovernance(
        agent_id="body_agent",
        permissions=("execute", "read_knowledge"),
        can_access=("knowledge_gateway:body",),
        cannot_access=("vault_filesystem", "personal_memory"),
        tools_called=(),
        audit_recorded=True,
    )
    response = AgentSDK(agent_id="body_agent", domain="body").response(
        summary="ok",
        reason="Recovery evidence suggests a lower load.",
        evidence=["KN-BODY-1"],
        confidence=0.8,
        governance=governance,
    )

    assert response.reason
    assert response.evidence == ["KN-BODY-1"]
    assert response.confidence == 0.8
    assert response.governance.cannot_access == ("vault_filesystem", "personal_memory")


def test_memory_scopes_are_separate_and_personal_memory_is_not_agent_writable(tmp_path: Path):
    from runtime_core.memory import MemoryManager

    memory = MemoryManager(tmp_path / "state")
    memory.record("body_agent", task="rule", output="x", scope="system")
    memory.record("body_agent", task="experience", output="y", scope="agent")

    assert memory.recent("body_agent", scope="system")[0].output == "x"
    assert memory.recent("body_agent", scope="agent")[0].output == "y"
    assert memory.scope_paths["system"].exists()
    assert memory.scope_paths["agent"].exists()
    with pytest.raises(PermissionError, match="personal memory"):
        memory.record("body_agent", task="self", output="z", scope="personal")


def test_knowledge_pipeline_captures_analyzes_generates_schema_and_librarian_proposals():
    from agents.knowledge_pipeline import KnowledgeLibrarian, KnowledgePipeline

    pipeline = KnowledgePipeline()
    captured = pipeline.capture(source="web", title="Sleep research", content="Sleep improves recovery.")
    analyzed = pipeline.analyze(captured)
    metadata = pipeline.generate_schema(analyzed)
    proposals = KnowledgeLibrarian().inspect([metadata, metadata])

    assert captured.destination == "00_Inbox"
    assert analyzed.summary == "Sleep improves recovery."
    assert metadata.metadata["status"] == "candidate"
    assert any(item["kind"] == "duplicate" for item in proposals)


def test_phase3_evaluation_checks_capability_boundary_and_explainability():
    from agents.evaluation import evaluate_boundary, evaluate_capability, evaluate_explainability, evaluate_response
    from agents.sdk import AgentResponse

    response = AgentResponse(
        summary="done",
        findings=["evidence"],
        proposals=[],
        next_actions=["review"],
        reason="because",
        evidence=["KN-1"],
        confidence=0.9,
    )
    assert evaluate_response(response).passed
    assert evaluate_capability(response).passed
    assert evaluate_explainability(response).passed
    assert evaluate_boundary().passed


def test_runtime_attaches_agent_governance_and_records_tool_calls(tmp_path: Path):
    from knowledge_system.gateway import ContextResponse
    from runtime_core import RuntimeKernel
    from runtime_core.models import AgentDefinition
    from agents.sdk import AgentSDK

    class Gateway:
        def get_context(self, task, *, agent_id, credential):
            return ContextResponse(knowledge=[], experience=[], principles=[])

    def handler(context):
        context.tools.call("body_os.read_snapshot")
        return AgentSDK(agent_id=context.agent_id, domain="body").response(
            summary="done", reason="snapshot", evidence=["body_os"], confidence=0.8
        )

    kernel = RuntimeKernel(gateway=Gateway(), state_path=tmp_path, local_model="local", cloud_model="cloud")
    kernel.tools.register("body_os.read_snapshot", lambda: {"recovery": "low"}, required_permission="use_tools")
    kernel.register_agent(AgentDefinition("body_agent", "Body Agent", "body", 2, "medium", ("execute", "read_knowledge", "use_tools"), handler))
    kernel.activate_agent("body_agent")

    output = kernel.execute("body_agent", credential="secret", task="assess").output
    assert output.governance.agent_id == "body_agent"
    assert output.governance.tools_called == ("body_os.read_snapshot",)
    assert output.governance.audit_recorded is True
    assert "personal_memory:11_Self_Model" in output.governance.cannot_access


def test_body_advisor_only_proposes_load_reduction_for_declining_recovery():
    from agents.body_advisor import assess_body_snapshot

    proposal = assess_body_snapshot({"training_load_trend": "increasing", "recovery_trend": "declining"})
    assert proposal["proposal_type"] == "training_adjustment"
    assert proposal["recommended_load"] == "reduce"
    assert proposal["requires_human_review"] is True
    assert proposal["status"] == "draft"


def test_study_planner_builds_map_path_and_review_suggestions():
    from agents.study_planner import build_learning_plan

    plan = build_learning_plan("Runtime governance", ["permissions", "audit", "gateway"])
    assert plan["goal"] == "Runtime governance"
    assert plan["knowledge_map"][0] == "permissions"
    assert plan["learning_path"] == ["permissions", "audit", "gateway"]
    assert plan["review_suggestions"]


def test_project_agent_creates_task_proposal_without_executing_gateway():
    from agents.project_execution import build_task_proposal

    proposal = build_task_proposal("Publish Phase 3 report", evidence=["evaluation:passed"])
    assert proposal["proposal_type"] == "task"
    assert proposal["status"] == "pending_human_review"
    assert proposal["execution_gateway"] == "feishu"
    assert proposal["executed"] is False


def test_librarian_reports_orphans_and_conflicts_as_drafts():
    from agents.knowledge_pipeline import KnowledgeLibrarian, KnowledgePipeline

    pipeline = KnowledgePipeline()
    first = pipeline.generate_schema(pipeline.analyze(pipeline.capture(source="pdf", title="Rule", content="A")))
    second = pipeline.generate_schema(pipeline.analyze(pipeline.capture(source="web", title="Rule", content="B")))
    proposals = KnowledgeLibrarian().inspect([first, second])

    assert any(item["kind"] == "orphan" for item in proposals)
    assert any(item["kind"] == "conflict" for item in proposals)
    assert all(item["status"] == "draft" for item in proposals)
