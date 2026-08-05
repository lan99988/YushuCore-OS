from __future__ import annotations

from datetime import date


def test_knowledge_importer_reviewer_and_auditor_complete_pipeline():
    from agents.knowledge_pipeline import (
        Classifier,
        Importer,
        KnowledgeAuditor,
        KnowledgePipeline,
        Reviewer,
    )

    pipeline = KnowledgePipeline()
    captured = pipeline.capture(source="image", title="Sleep", content="Sleep improves recovery.")
    markdown = Importer().to_markdown(captured)
    classified = Classifier().classify(pipeline.analyze(captured))
    schema = pipeline.generate_schema(pipeline.analyze(captured))
    review = Reviewer().review(schema)
    audit = KnowledgeAuditor().audit(
        [schema],
        today=date(2026, 8, 5),
    )

    assert "source: image" in markdown
    assert classified["suggested_domain"] == "body"
    assert review["status"] == "review_required"
    assert isinstance(audit, list)


def test_knowledge_auditor_reports_conflicting_viewpoints():
    from agents.knowledge_pipeline import KnowledgeAuditor, KnowledgePipeline

    pipeline = KnowledgePipeline()
    first = pipeline.generate_schema(
        pipeline.analyze(
            pipeline.capture(source="manual", title="Rule", content="Sleep helps.")
        )
    )
    second = pipeline.generate_schema(
        pipeline.analyze(
            pipeline.capture(source="manual", title="Rule", content="Sleep hurts.")
        )
    )

    findings = KnowledgeAuditor().audit([first, second])

    assert any(item["kind"] == "conflict" for item in findings)


def test_memory_manager_keeps_logical_agent_memory_separate(tmp_path):
    from runtime_core.memory import MemoryManager

    memory = MemoryManager(tmp_path / "state")
    entry = memory.record("body_agent", task="training", output="reduce load")

    assert entry.scope == "agent"
    assert memory.agent_memory_path("body_agent").exists()
    assert memory.recent("body_agent", scope="agent")[0].output == "reduce load"


def test_agent_permission_matrix_distinguishes_allowed_request_and_denied():
    from runtime_core.models import AgentDefinition
    from runtime_core.permissions import AgentPermissionMatrix

    definition = AgentDefinition(
        "body_agent",
        "Body Agent",
        "body",
        2,
        "medium",
        ("execute", "read_knowledge", "propose_change"),
        lambda context: None,
    )
    matrix = AgentPermissionMatrix()

    assert matrix.check(definition, "knowledge").status == "allowed"
    assert matrix.check(definition, "cognition").status == "request"
    assert matrix.check(definition, "modify").status == "request"


def test_event_bus_relays_agent_events_without_direct_agent_calls():
    from runtime_core.collaboration import AgentEventRelay
    from runtime_core.events import EventBus

    bus = EventBus()
    relay = AgentEventRelay(bus)
    received: list[dict] = []
    relay.subscribe("study_agent", "body_low_energy", received.append)

    relay.emit(
        "body_agent",
        "body_low_energy",
        {"recovery_score": 0.35},
        correlation_id="corr-3",
    )

    assert received[0]["source_agent"] == "body_agent"
    assert received[0]["target_agent"] == "study_agent"
    assert received[0]["payload"]["recovery_score"] == 0.35


def test_future_agent_catalog_is_safe_and_inactive():
    from agents.future import future_agent_catalog, future_handler_map

    catalog = future_agent_catalog()

    assert {item.agent_id for item in catalog} == {
        "health_agent",
        "research_agent",
        "file_agent",
        "calendar_agent",
        "communication_agent",
    }
    assert all(item.active is False for item in catalog)
    assert all("execute" not in item.permissions for item in catalog)
    assert set(future_handler_map()) == {
        "health_agent_handler",
        "research_agent_handler",
        "file_agent_handler",
        "calendar_agent_handler",
        "communication_agent_handler",
    }


def test_body_advisor_exposes_training_recovery_risk_and_trend_outputs():
    from agents.body_advisor import assess_body_snapshot

    result = assess_body_snapshot(
        {
            "training_load_trend": "increasing",
            "recovery_trend": "declining",
            "sleep_hours": 5.5,
            "subjective_fatigue": 8,
        }
    )

    assert result["training_suggestion"] == "reduce"
    assert result["recovery_suggestion"]
    assert result["risk_flags"]
    assert result["trend_analysis"]


def test_study_plan_includes_tasks_weak_points_and_knowledge_connections():
    from agents.study_planner import build_learning_plan

    result = build_learning_plan(
        "Runtime governance",
        ["permissions", "audit", "gateway"],
    )

    assert result["task_suggestions"]
    assert result["weak_points"] == ["permissions"]
    assert result["knowledge_connections"]


def test_project_task_proposal_contains_approval_metadata():
    from agents.project_execution import build_project_plan, build_task_proposal

    result = build_task_proposal(
        "Publish report",
        evidence=["evaluation:passed"],
        project_id="P-1",
        assignee="owner",
        due_at="2026-08-10",
    )

    assert result["approval"]["status"] == "pending_human_review"
    assert result["project_id"] == "P-1"
    assert result["assignee"] == "owner"
    assert result["due_at"] == "2026-08-10"

    plan = build_project_plan(
        "Phase 4",
        task_status={"docs": "done", "tests": "blocked"},
        progress=0.5,
    )
    assert plan["project_plan"]
    assert plan["risk_analysis"]
    assert plan["task_suggestions"]


def test_skill_catalog_supports_phase4_extension_without_replacing_existing_skills():
    from agents.sdk import SkillSpec
    from agents.skills import SkillCatalog

    catalog = SkillCatalog.for_phase3()
    catalog.register(
        SkillSpec(
            skill_id="body_recovery_prediction",
            name="Recovery Prediction",
            domain="body",
            required_permissions=("read_knowledge", "use_tools"),
            risk_level="medium",
        )
    )

    assert catalog.for_domain("body")[-1].skill_id == "body_recovery_prediction"
    assert catalog.for_domain("knowledge")[0].skill_id == "knowledge_analysis"


def test_body_low_energy_event_creates_study_and_project_proposals():
    from agents.collaboration import build_body_low_energy_proposals

    result = build_body_low_energy_proposals(
        {"event": "body_low_energy", "payload": {"recovery_trend": "declining"}}
    )

    assert result["study"]["proposal_type"] == "learning_adjustment"
    assert result["project"]["proposal_type"] == "task_adjustment"
    assert result["study"]["status"] == "draft"
    assert result["project"]["status"] == "pending_human_review"


def test_phase4_skill_catalog_contains_text_specified_agent_skills():
    from agents.registry import phase4_skill_catalog

    catalog = phase4_skill_catalog()

    assert {skill.skill_id for skill in catalog.for_domain("knowledge")} >= {
        "knowledge_import",
        "knowledge_audit",
    }
    assert {skill.skill_id for skill in catalog.for_domain("body")} >= {
        "body_recovery_prediction",
        "body_running_analysis",
    }
    assert {skill.skill_id for skill in catalog.for_domain("study")} >= {
        "study_spaced_repetition",
        "study_knowledge_mapping",
    }
