from __future__ import annotations

import pytest


def test_phase4_agent_request_and_result_round_trip():
    from runtime_core.models import AgentRequest, AgentResult, AutonomyLevel

    request = AgentRequest(
        task_id="TASK-001",
        requester="human",
        agent_id="body_agent",
        goal="generate training plan",
        context="last_30_days_training",
        constraints=("read only", "proposal only"),
        permission="approved",
    )
    result = AgentResult(
        task_id=request.task_id,
        agent_id=request.agent_id,
        result="Training volume should reduce 20%",
        confidence=0.85,
        sources=("body/weekly.md",),
        proposals=({"type": "training_adjustment", "status": "draft"},),
        actions=("submit proposal",),
    )

    assert request.agent_id == "body_agent"
    assert result.task_id == "TASK-001"
    assert result.confidence == 0.85
    assert AutonomyLevel.LEVEL_2.value == 2


def test_agent_request_rejects_invalid_identity_permission_and_network_mode():
    from runtime_core.models import AgentRequest

    with pytest.raises(ValueError, match="task_id"):
        AgentRequest(task_id="", requester="human", agent_id="body_agent", goal="goal", context="context")
    with pytest.raises(ValueError, match="permission"):
        AgentRequest(
            task_id="TASK-INVALID",
            requester="human",
            agent_id="body_agent",
            goal="goal",
            context="context",
            permission="granted",
        )
    with pytest.raises(ValueError, match="network_mode"):
        AgentRequest(
            task_id="TASK-INVALID",
            requester="human",
            agent_id="body_agent",
            goal="goal",
            context="context",
            network_mode="ONLINE",
        )


def test_agent_result_rejects_out_of_range_confidence():
    from runtime_core.models import AgentResult

    with pytest.raises(ValueError, match="confidence"):
        AgentResult(task_id="TASK-INVALID", agent_id="body_agent", result="x", confidence=1.1)


def test_agent_sdk_response_rejects_out_of_range_confidence():
    from agents.sdk import AgentSDK

    with pytest.raises(ValueError, match="confidence"):
        AgentSDK(agent_id="body_agent", domain="body").response(
            summary="x", confidence=-0.1
        )


def test_phase4_agent_sdk_can_build_request_and_response():
    from agents.sdk import AgentSDK

    sdk = AgentSDK(agent_id="knowledge_agent", domain="knowledge")

    request = sdk.request(
        task_id="TASK-002",
        requester="human",
        goal="analyze sleep note",
        context="sleep.md",
        constraints=("markdown first",),
        permission="approved",
    )
    response = sdk.response_from_request(
        request,
        result="Sleep note is ready for review",
        confidence=0.9,
        sources=("05_Domains/Body/sleep.md",),
        proposals=({"type": "review", "status": "draft"},),
        actions=("human review",),
    )

    assert request.agent_id == "knowledge_agent"
    assert response.task_id == "TASK-002"
    assert response.proposals[0]["status"] == "draft"


def test_runtime_executes_standard_agent_request(tmp_path):
    from knowledge_system.gateway import ContextResponse
    from runtime_core import AgentDefinition, AgentRequest, RuntimeKernel
    from agents.sdk import AgentSDK

    class Gateway:
        def get_context(self, task, *, agent_id, credential):
            return ContextResponse(knowledge=[], experience=[], principles=[])

    kernel = RuntimeKernel(
        gateway=Gateway(),
        state_path=tmp_path / "state",
        local_model="local",
        cloud_model="cloud",
    )
    kernel.register_agent(
        AgentDefinition(
            "body_agent",
            "Body Agent",
            "body",
            2,
            "medium",
            ("execute", "read_knowledge"),
            lambda context: AgentSDK(agent_id="body_agent", domain="body").response(
                summary="done",
                reason="runtime request",
                evidence=["body"],
                confidence=0.8,
            ),
        )
    )
    kernel.activate_agent("body_agent")

    request = AgentRequest(
        task_id="TASK-003",
        requester="human",
        agent_id="body_agent",
        goal="assess recovery",
        context="body snapshot",
        permission="approved",
        correlation_id="corr-5",
    )
    result = kernel.execute_request(request, credential="secret")

    assert result.task_id == "TASK-003"
    assert result.agent_id == "body_agent"
    assert result.confidence == 0.8
    assert result.correlation_id == "corr-5"
    assert result.governance.agent_id == "body_agent"


def test_runtime_context_exposes_event_relay_but_not_other_agents(tmp_path):
    from knowledge_system.gateway import ContextResponse
    from runtime_core import AgentDefinition, RuntimeKernel

    class Gateway:
        def get_context(self, task, *, agent_id, credential):
            return ContextResponse(knowledge=[], experience=[], principles=[])

    kernel = RuntimeKernel(
        gateway=Gateway(),
        state_path=tmp_path / "state",
        local_model="local",
        cloud_model="cloud",
    )

    def handler(context):
        assert context.collaboration is kernel.collaboration
        assert not hasattr(context, "agents")
        context.collaboration.emit(
            context.agent_id,
            "body_low_energy",
            {"recovery_score": 0.35},
            correlation_id="corr-4",
        )
        return "ok"

    kernel.register_agent(
        AgentDefinition(
            "body_agent",
            "Body Agent",
            "body",
            2,
            "medium",
            ("execute", "read_knowledge"),
            handler,
        )
    )
    kernel.activate_agent("body_agent")
    kernel.execute("body_agent", credential="secret", task="emit")

    assert any(event["event"] == "body_low_energy" for event in kernel.events.history)


def test_body_agent_emits_low_energy_event_through_runtime(tmp_path):
    from knowledge_system.gateway import ContextResponse
    from runtime_core import AgentDefinition, RuntimeKernel
    from agents.body import body_agent_handler

    class Gateway:
        def get_context(self, task, *, agent_id, credential):
            return ContextResponse(knowledge=[], experience=[], principles=[])

    kernel = RuntimeKernel(
        gateway=Gateway(),
        state_path=tmp_path / "state",
        local_model="local",
        cloud_model="cloud",
    )
    kernel.tools.register(
        "body_os.read_snapshot",
        lambda: {"training_load_trend": "increasing", "recovery_trend": "declining"},
        required_permission="use_tools",
    )
    kernel.register_agent(
        AgentDefinition(
            "body_agent",
            "Body Agent",
            "body",
            2,
            "medium",
            ("execute", "read_knowledge", "use_tools"),
            body_agent_handler,
        )
    )
    kernel.activate_agent("body_agent")

    kernel.execute("body_agent", credential="secret", task="body", correlation_id="corr-6")

    event = [item for item in kernel.events.history if item["event"] == "body_low_energy"][0]
    assert event["source_agent"] == "body_agent"
    assert event["correlation_id"] == "corr-6"
