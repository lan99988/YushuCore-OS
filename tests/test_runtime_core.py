from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_plugins import (
    ActivationState,
    Availability,
    PluginManifest,
    PluginRegistry,
    RiskLevel,
)
from knowledge_system.gateway import (
    AgentPolicy,
    KnowledgeGateway,
    ReviewerPolicy,
)
from runtime_core import (
    AccessRequestDenied,
    ActionAuthority,
    AgentDefinition,
    AgentLifecycleError,
    ModelRouter,
    PermissionDenied,
    PlannedAction,
    RuntimeKernel,
)
from runtime_core.audit import canonical_payload_digest


BODY_CREDENTIAL = "body-secret"
STUDY_CREDENTIAL = "study-secret"
OWNER_CREDENTIAL = "owner-secret"


def _plugin_registry(
    *,
    plugin_id: str,
    capability: str,
    permissions: tuple[str, ...],
    writes: tuple[str, ...] = (),
    risk_level: RiskLevel = RiskLevel.LOW,
) -> PluginRegistry:
    manifest = PluginManifest(
        plugin_id=plugin_id,
        name=f"{plugin_id.title()} Plugin",
        version="1.0.0",
        purpose="Runtime authorization test plugin",
        domain=plugin_id,
        provides=(capability,),
        reads=(),
        writes=writes,
        dependencies=(),
        permissions=permissions,
        risk_level=risk_level,
        activation_mode="always",
        availability=Availability.INSTALLED,
        enabled=True,
        activation_state=ActivationState.ACTIVE,
    )
    return PluginRegistry.from_manifests((manifest,))


def _write_note(
    root: Path,
    relative: str,
    *,
    node_id: str,
    domain: str,
    agent: str,
    status: str = "validated",
    sensitivity: str = "level_1",
    body: str = "sleep improves learning efficiency",
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {node_id}
type: knowledge
title: {node_id}
domain: {domain}
layer: knowledge
source: manual
author: owner
created: 2026-08-04
updated: 2026-08-04
status: {status}
confidence: 0.85
agent_access:
  - {agent}
sensitivity: {sensitivity}
version: "1.0"
relations: []
---
# {node_id}

{body}
""",
        encoding="utf-8",
    )
    return path


def _gateway(tmp_path: Path, *, body_max_sensitivity: str = "level_2") -> KnowledgeGateway:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "05_Domains/Body/sleep.md",
        node_id="KN-BODY-1",
        domain="body",
        agent="body_agent",
    )
    _write_note(
        vault,
        "05_Domains/Study/study.md",
        node_id="KN-STUDY-1",
        domain="study",
        agent="study_agent",
    )
    _write_note(
        vault,
        "05_Domains/Body/core.md",
        node_id="KN-CORE-1",
        domain="body",
        agent="body_agent",
        sensitivity="level_3",
    )
    return KnowledgeGateway(
        vault,
        state_path=tmp_path / "gateway_state",
        policies={
            "body_agent": AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity=body_max_sensitivity,
                max_proposal_sensitivity="level_3",
            ),
            "study_agent": AgentPolicy(
                allowed_folders=("05_Domains/Study",),
                allowed_domains=("study",),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
        },
        agent_credentials={
            "body_agent": BODY_CREDENTIAL,
            "study_agent": STUDY_CREDENTIAL,
        },
        reviewers={
            "owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True),
        },
    )


def test_runtime_kernel_executes_agent_with_context_tools_memory_and_logging(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.tools.register("shout", lambda text: text.upper(), required_permission="use_tools")

    def handler(context):
        return {
            "knowledge_ids": [node.id for node in context.knowledge],
            "model_provider": context.model.provider,
            "tool_result": context.tools.call("shout", text="ready"),
            "memory_size": context.memory.size("body_agent"),
        }

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "use_tools"),
            handler=handler,
        )
    )
    kernel.activate_agent("body_agent")

    result = kernel.execute(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="sleep",
        complexity="standard",
        network_mode="OFF",
    )

    assert result.output == {
        "knowledge_ids": ["KN-BODY-1"],
        "model_provider": "local",
        "tool_result": "READY",
        "memory_size": 0,
    }
    assert kernel.memory.size("body_agent") == 1

    log_lines = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in log_lines]
    assert [event["event"] for event in events] == [
        "agent_activated",
        "model_route_selected",
        "agent_started",
        "tool_called",
        "agent_completed",
    ]
    assert events[0]["agent_id"] == "body_agent"
    assert events[1]["provider"] == "local"
    assert events[1]["reason"] == "local_first"
    assert events[3] == {
        "event": "tool_called",
        "agent_id": "body_agent",
        "tool": "shout",
    }
    assert events[4]["model"]["provider"] == "local"


def test_runtime_kernel_requires_activation_before_execution(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: "active",
        )
    )

    with pytest.raises(AgentLifecycleError, match="agent_not_active"):
        kernel.execute(
            "body_agent",
            credential=BODY_CREDENTIAL,
            task="sleep",
        )

    kernel.activate_agent("body_agent")
    assert kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep").output == "active"

    kernel.deactivate_agent("body_agent")
    with pytest.raises(AgentLifecycleError, match="agent_not_active"):
        kernel.execute(
            "body_agent",
            credential=BODY_CREDENTIAL,
            task="sleep",
        )


def test_runtime_kernel_loads_agent_registry_from_yaml_config(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    config_path = tmp_path / "agents.yaml"
    config_path.write_text(
        """agents:
  - agent_id: body_agent
    name: Body Runtime Agent
    domain: body
    description: Reads body knowledge and proposes approved changes.
    autonomy_level: 2
    risk_level: medium
    permissions:
      - execute
      - read_knowledge
      - propose_change
    model_policy: local_first
    handler: body_handler
""",
        encoding="utf-8",
    )

    kernel.load_agents_from_file(
        config_path,
        handlers={"body_handler": lambda context: [node.id for node in context.knowledge]},
    )

    loaded = kernel.registry.get("body_agent")
    assert loaded.description == "Reads body knowledge and proposes approved changes."
    assert loaded.model_policy == "local_first"

    kernel.activate_agent("body_agent")
    result = kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    assert result.output == ["KN-BODY-1"]


def test_runtime_kernel_blocks_unauthorized_proposal_requests(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )

    kernel.register_agent(
        AgentDefinition(
            agent_id="study_agent",
            name="Study Runtime Agent",
            domain="study",
            autonomy_level=1,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("study_agent")

    with pytest.raises(PermissionDenied, match="propose_change_denied"):
        kernel.request_update(
            "study_agent",
            credential=STUDY_CREDENTIAL,
            target_id="KN-STUDY-1",
            old="sleep improves learning efficiency",
            new="sleep and review improve learning efficiency",
            reason="add a study note",
            confidence=0.7,
            risk="medium",
        )


def test_runtime_kernel_audits_denied_proposal_requests_without_logging_change_content(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )

    kernel.register_agent(
        AgentDefinition(
            agent_id="study_agent",
            name="Study Runtime Agent",
            domain="study",
            autonomy_level=1,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("study_agent")

    with pytest.raises(PermissionDenied, match="propose_change_denied"):
        kernel.request_update(
            "study_agent",
            credential=STUDY_CREDENTIAL,
            target_id="KN-STUDY-1",
            old="sleep improves learning efficiency",
            new="sleep and review improve learning efficiency",
            reason="proposal with secret token 123",
            confidence=0.7,
            risk="medium",
            correlation_id="corr-proposal-denied",
        )

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    denial_event = next(event for event in events if event["event"] == "proposal_denied")
    assert denial_event["action"] == "request_update"
    assert denial_event["agent_id"] == "study_agent"
    assert denial_event["target_id"] == "KN-STUDY-1"
    assert denial_event["error_type"] == "PermissionDenied"
    assert denial_event["correlation_id"] == "corr-proposal-denied"
    assert "sleep and review improve learning efficiency" not in event_log
    assert "secret token 123" not in event_log


def test_runtime_kernel_audits_denied_tool_calls_without_logging_tool_arguments(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.tools.register("sensitive_tool", lambda secret: secret, required_permission="use_tools")
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: context.tools.call("sensitive_tool", secret="do-not-log"),
        )
    )
    kernel.activate_agent("body_agent")

    with pytest.raises(PermissionDenied, match="use_tools_denied"):
        kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    log_lines = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in log_lines]
    assert events[-2] == {
        "event": "tool_denied",
        "agent_id": "body_agent",
        "tool": "sensitive_tool",
        "reason": "use_tools_denied",
    }
    assert "do-not-log" not in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")


def test_runtime_kernel_audits_unknown_tool_calls_without_logging_tool_arguments(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "use_tools"),
            handler=lambda context: context.tools.call("unregistered_tool", secret="do-not-log"),
        )
    )
    kernel.activate_agent("body_agent")

    with pytest.raises(KeyError, match="Unknown tool: unregistered_tool"):
        kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    assert events[-2] == {
        "event": "tool_denied",
        "agent_id": "body_agent",
        "tool": "unregistered_tool",
        "reason": "unknown_tool",
    }
    assert "do-not-log" not in event_log


def test_runtime_kernel_audits_agent_failures_without_logging_exception_message(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
        retry_max_attempts=2,
    )

    def handler(context):
        raise RuntimeError("secret-token-should-not-be-logged")

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=handler,
        )
    )
    kernel.activate_agent("body_agent")

    with pytest.raises(RuntimeError, match="secret-token-should-not-be-logged"):
        kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    retry_event = next(event for event in events if event["event"] == "agent_retry")
    failed_event = next(event for event in events if event["event"] == "agent_failed")
    assert retry_event["error_type"] == "RuntimeError"
    assert failed_event["error_type"] == "RuntimeError"
    assert "error" not in retry_event
    assert "error" not in failed_event
    assert "secret-token-should-not-be-logged" not in event_log


def test_runtime_kernel_audits_failed_tool_calls_without_logging_arguments(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.tools.register(
        "explode",
        lambda text: (_ for _ in ()).throw(RuntimeError("tool-secret-should-not-leak")),
        required_permission="use_tools",
    )

    def handler(context):
        return context.tools.call("explode", text="token-123")

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "use_tools"),
            handler=handler,
        )
    )
    kernel.activate_agent("body_agent")

    with pytest.raises(RuntimeError, match="tool-secret-should-not-leak"):
        kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    failed_event = next(event for event in events if event["event"] == "tool_failed")
    assert failed_event["agent_id"] == "body_agent"
    assert failed_event["tool"] == "explode"
    assert failed_event["error_type"] == "RuntimeError"
    assert "tool-secret-should-not-leak" not in event_log
    assert "token-123" not in event_log


def test_runtime_kernel_delegates_approval_workflow_to_gateway(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "propose_change"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")

    proposal = kernel.request_update(
        "body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="sleep improves learning efficiency",
        new="sleep and recovery improve learning efficiency",
        reason="update body note",
        confidence=0.8,
        risk="medium",
    )

    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    assert "sleep improves learning efficiency" in target.read_text(encoding="utf-8")

    approved = kernel.approve_change(
        proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
    )

    assert approved.status == "approved"
    assert "sleep and recovery improve learning efficiency" in target.read_text(encoding="utf-8")


def test_runtime_kernel_audits_proposal_lifecycle_without_logging_change_content(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "propose_change"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")

    proposal = kernel.request_update(
        "body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="sleep improves learning efficiency",
        new="sleep and recovery improve learning efficiency",
        reason="propose update with secret token 123",
        confidence=0.8,
        risk="medium",
    )
    rejected_proposal = kernel.request_update(
        "body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="sleep improves learning efficiency",
        new="sleep and recovery improve learning efficiency",
        reason="reject with secret note 456",
        confidence=0.8,
        risk="medium",
    )
    expired_proposal = kernel.request_update(
        "body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="sleep improves learning efficiency",
        new="sleep and recovery improve learning efficiency",
        reason="expire with secret note 789",
        confidence=0.8,
        risk="medium",
    )
    approved = kernel.approve_change(
        proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
    )
    rejected = kernel.reject_change(
        rejected_proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
        reason="reject with secret note 456",
    )
    expired = kernel.expire_change(
        expired_proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
        reason="expire with secret note 789",
    )

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    assert [event["event"] for event in events if event["event"].startswith("proposal_")] == [
        "proposal_requested",
        "proposal_requested",
        "proposal_requested",
        "proposal_approved",
        "proposal_rejected",
        "proposal_expired",
    ]
    request_event = next(event for event in events if event["event"] == "proposal_requested")
    approve_event = next(event for event in events if event["event"] == "proposal_approved")
    reject_event = next(event for event in events if event["event"] == "proposal_rejected")
    expire_event = next(event for event in events if event["event"] == "proposal_expired")
    assert request_event["proposal_id"] == proposal.proposal_id
    assert request_event["target_id"] == "KN-BODY-1"
    assert request_event["confidence"] == 0.8
    assert request_event["risk"] == "medium"
    assert approve_event["proposal_id"] == proposal.proposal_id
    assert approve_event["reviewer"] == "owner"
    assert rejected.status == "rejected"
    assert reject_event["proposal_id"] == rejected_proposal.proposal_id
    assert reject_event["reviewer"] == "owner"
    assert expired.status == "expired"
    assert expire_event["proposal_id"] == expired_proposal.proposal_id
    assert expire_event["reviewer"] == "owner"
    assert "sleep and recovery improve learning efficiency" not in event_log
    assert "secret token 123" not in event_log
    assert "secret note 456" not in event_log
    assert "secret note 789" not in event_log


def test_runtime_kernel_records_and_approves_access_requests(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "request_access"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")

    request = kernel.request_access(
        "body_agent",
        resource="11_Self_Model/core-values.md",
        reason="Need explicit owner approval before reading core self model.",
        sensitivity="level_4",
    )

    assert request.status == "pending"
    assert request.agent_id == "body_agent"
    assert request.sensitivity == "level_4"
    assert (tmp_path / "runtime_state" / "access_requests" / f"{request.request_id}.json").exists()

    approved = kernel.approve_access_request(
        request.request_id,
        reviewer="owner",
        reason="Approved for one reviewed task.",
    )

    assert approved.status == "approved"
    assert approved.reviewer == "owner"
    events = [
        json.loads(line)
        for line in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events[-2:]] == [
        "access_request_created",
        "access_request_approved",
    ]


def test_runtime_kernel_audits_monitor_and_update_without_logging_details_values(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")

    monitor = kernel.monitor_agent(
        "body_agent",
        check=lambda agent: {"healthy": True, "secret": "token-123"},
    )
    update = kernel.update_agent(
        "body_agent",
        changes={"version": "1.1", "secret": "token-456"},
    )

    assert monitor.status == "monitored"
    assert update.status == "updated"
    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    monitored_event = next(event for event in events if event["event"] == "agent_monitored")
    updated_event = next(event for event in events if event["event"] == "agent_updated")
    assert monitored_event["fields"] == ["healthy", "secret"]
    assert updated_event["fields"] == ["secret", "version"]
    assert "token-123" not in event_log
    assert "token-456" not in event_log


def test_runtime_kernel_audits_denied_access_request_creation_without_logging_resource_content(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="study_agent",
            name="Study Runtime Agent",
            domain="study",
            autonomy_level=1,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("study_agent")

    with pytest.raises(PermissionDenied, match="request_access_denied"):
        kernel.request_access(
            "study_agent",
            resource="11_Self_Model/core-values.md",
            reason="Need explicit owner approval for secret token 123.",
            sensitivity="level_4",
        )

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    denial_event = next(event for event in events if event["event"] == "access_request_denied")
    assert denial_event["agent_id"] == "study_agent"
    assert denial_event["resource"] == "11_Self_Model/core-values.md"
    assert denial_event["error_type"] == "PermissionDenied"
    assert "secret token 123" not in event_log


def test_runtime_kernel_uses_approved_access_request_for_temporary_context_grant(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "request_access"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")

    normal_context = kernel.get_context(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="core",
    )
    assert [node.id for node in normal_context.knowledge] == []

    request = kernel.request_access(
        "body_agent",
        resource="05_Domains/Body/core.md",
        reason="Need owner-approved access to a high-sensitivity body principle.",
        sensitivity="level_3",
    )

    with pytest.raises(AccessRequestDenied, match="access_request_not_approved"):
        kernel.get_context_with_access(
            "body_agent",
            credential=BODY_CREDENTIAL,
            task="core",
            access_request_id=request.request_id,
        )
    events = [
        json.loads(line)
        for line in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "access_grant_denied"
    assert events[-1]["request_id"] == request.request_id
    assert events[-1]["reason"] == "access_request_not_approved"

    approved = kernel.approve_access_request(
        request.request_id,
        reviewer="owner",
        reason="Approved for one reviewed task.",
    )

    granted_context = kernel.get_context_with_access(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="core",
        access_request_id=approved.request_id,
    )

    assert [node.id for node in granted_context.knowledge] == ["KN-CORE-1"]
    events = [
        json.loads(line)
        for line in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "access_grant_used"
    assert events[-1]["resource"] == "05_Domains/Body/core.md"


def test_runtime_access_grant_is_single_use_and_persistently_marked_used(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "request_access"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")
    request = kernel.request_access(
        "body_agent",
        resource="05_Domains/Body/core.md",
        reason="Need single-use high-sensitivity access.",
        sensitivity="level_3",
    )
    approved = kernel.approve_access_request(
        request.request_id,
        reviewer="owner",
        reason="Approved for one read.",
    )

    first_context = kernel.get_context_with_access(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="core",
        access_request_id=approved.request_id,
    )

    assert [node.id for node in first_context.knowledge] == ["KN-CORE-1"]
    assert kernel.access_requests.load(approved.request_id).status == "used"
    with pytest.raises(AccessRequestDenied, match="access_request_already_used"):
        kernel.get_context_with_access(
            "body_agent",
            credential=BODY_CREDENTIAL,
            task="core",
            access_request_id=approved.request_id,
        )
    events = [
        json.loads(line)
        for line in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "access_grant_denied"
    assert events[-1]["request_id"] == approved.request_id
    assert events[-1]["reason"] == "access_request_already_used"


def test_runtime_kernel_rejects_access_grant_for_different_agent(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "request_access"),
            handler=lambda context: None,
        )
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="study_agent",
            name="Study Runtime Agent",
            domain="study",
            autonomy_level=1,
            risk_level="medium",
            permissions=("execute", "read_knowledge", "request_access"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("body_agent")
    kernel.activate_agent("study_agent")
    request = kernel.request_access(
        "body_agent",
        resource="05_Domains/Body/core.md",
        reason="Need owner-approved access.",
        sensitivity="level_3",
    )
    approved = kernel.approve_access_request(
        request.request_id,
        reviewer="owner",
        reason="Approved for body agent only.",
    )

    with pytest.raises(AccessRequestDenied, match="access_request_agent_mismatch"):
        kernel.get_context_with_access(
            "study_agent",
            credential=STUDY_CREDENTIAL,
            task="core",
            access_request_id=approved.request_id,
        )


def test_runtime_kernel_denies_access_request_without_runtime_permission(tmp_path: Path):
    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="study_agent",
            name="Study Runtime Agent",
            domain="study",
            autonomy_level=1,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: None,
        )
    )
    kernel.activate_agent("study_agent")

    with pytest.raises(PermissionDenied, match="request_access_denied"):
        kernel.request_access(
            "study_agent",
            resource="11_Self_Model/core-values.md",
            reason="try to read core self model",
            sensitivity="level_4",
        )


def test_model_router_uses_local_first_and_cloud_for_complex_tasks():
    router = ModelRouter(local_model="qwen3:8b", cloud_model="deepseek-reasoner")

    local_route = router.select(complexity="standard", network_mode="OFF")
    cloud_route = router.select(complexity="deep", network_mode="ASSIST")
    sensitive_route = router.select(
        complexity="deep",
        network_mode="ASSIST",
        max_context_sensitivity="level_4",
    )

    assert local_route.provider == "local"
    assert local_route.model_name == "qwen3:8b"
    assert cloud_route.provider == "cloud"
    assert cloud_route.model_name == "deepseek-reasoner"
    assert sensitive_route.provider == "local"
    assert sensitive_route.reason == "sensitive_context_requires_local_model"


def test_runtime_kernel_keeps_level_3_context_local_when_assist_requests_cloud(tmp_path: Path):
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path, body_max_sensitivity="level_3"),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: context.model,
        )
    )
    kernel.activate_agent("body_agent")

    result = kernel.execute(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="core",
        complexity="deep",
        network_mode="ASSIST",
    )

    assert result.model.provider == "local"
    assert result.model.reason == "sensitive_context_requires_local_model"


def test_runtime_kernel_agent_events_have_a_correlated_operation_id_by_default(tmp_path: Path):
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: "ready",
        )
    )

    kernel.activate_agent("body_agent")
    kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    events = kernel.events.history
    activation = next(event for event in events if event["event"] == "agent_activated")
    execution_events = [
        event
        for event in events
        if event["event"] in {"model_route_selected", "agent_started", "agent_completed"}
    ]
    assert activation["correlation_id"]
    assert all(event["correlation_id"] for event in execution_events)
    assert len({event["correlation_id"] for event in execution_events}) == 1


def test_runtime_kernel_audits_model_route_selection_without_logging_context(tmp_path: Path):
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path, body_max_sensitivity="level_3"),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: context.model.provider,
        )
    )
    kernel.activate_agent(
        "body_agent", correlation_id="corr-runtime-observability"
    )

    kernel.execute(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="core",
        complexity="deep",
        network_mode="ASSIST",
        correlation_id="corr-runtime-observability",
    )

    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in event_log.splitlines()]
    route_event = next(event for event in events if event["event"] == "model_route_selected")
    assert route_event["agent_id"] == "body_agent"
    assert route_event["provider"] == "local"
    assert route_event["reason"] == "sensitive_context_requires_local_model"
    assert route_event["network_mode"] == "ASSIST"
    assert route_event["complexity"] == "deep"
    assert route_event["max_context_sensitivity"] == "level_3"
    assert route_event["correlation_id"] == "corr-runtime-observability"
    assert all(
        event.get("correlation_id") == "corr-runtime-observability"
        for event in events
        if event["event"].startswith("agent_")
    )
    assert "knowledge" not in route_event
    assert "sleep improves learning efficiency" not in event_log


def test_runtime_kernel_authorizes_new_planned_action_and_writes_full_audit(tmp_path: Path):
    plugin_registry = _plugin_registry(
        plugin_id="records",
        capability="records.write",
        permissions=("records.write",),
    )
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
        plugin_registry=plugin_registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "records.write"),
            handler=lambda context: None,
        )
    )
    sentinel = "PRIVATE-BODY-CONTENT-8f31"
    action = PlannedAction(
        action_id="action-1",
        plugin_id="records",
        capability="records.write",
        authority=ActionAuthority.AUTONOMOUS,
        reversible=True,
        external_effect=False,
        affects_commitment=False,
        risk="low",
        payload_digest=canonical_payload_digest({"body": sentinel}),
        operation=f"update_{sentinel}",
        resource=f"internal:{sentinel}",
        required_permissions=("records.write",),
    )

    decision = kernel.authorize_action(
        "body_agent",
        action,
        correlation_id="corr-action-1",
    )

    assert decision.allowed is True
    assert decision.approval_required is False
    saved = json.loads(
        (tmp_path / "runtime_state" / "audit.jsonl").read_text(encoding="utf-8")
    )
    assert set(saved) == {
        "actor",
        "operation",
        "resource",
        "decision",
        "reason_code",
        "correlation_id",
        "timestamp",
        "result",
        "plugin_id",
        "capability",
        "payload_digest",
    }
    assert saved["decision"] == "autonomous"
    assert saved["result"] == "allowed"
    assert saved["operation"] == "records.write"
    assert saved["resource"] == "plugin:records"
    assert saved["payload_digest"] == action.payload_digest
    assert sentinel not in json.dumps(saved, ensure_ascii=False)


def test_runtime_kernel_approval_decision_does_not_raise_agent_autonomy(tmp_path: Path):
    plugin_registry = _plugin_registry(
        plugin_id="social",
        capability="messaging.send",
        permissions=("messaging.send",),
        writes=("external.message",),
        risk_level=RiskLevel.MEDIUM,
    )
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
        plugin_registry=plugin_registry,
    )
    agent = AgentDefinition(
        agent_id="body_agent",
        name="Body Runtime Agent",
        domain="body",
        autonomy_level=2,
        risk_level="medium",
        permissions=("execute", "messaging.send"),
        handler=lambda context: None,
    )
    kernel.register_agent(agent)
    action = PlannedAction(
        action_id="action-message",
        plugin_id="social",
        capability="messaging.send",
        authority=ActionAuthority.AUTONOMOUS,
        reversible=True,
        external_effect=True,
        affects_commitment=True,
        risk="medium",
        payload_digest="b" * 64,
        operation="send_message",
        resource="external:contact",
        required_permissions=("messaging.send",),
    )

    decision = kernel.authorize_action(
        "body_agent",
        action,
        correlation_id="corr-action-2",
    )

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.effective_authority is ActionAuthority.APPROVAL_REQUIRED
    assert kernel.registry.get("body_agent").autonomy_level == 2
    saved = json.loads(
        (tmp_path / "runtime_state" / "audit.jsonl").read_text(encoding="utf-8")
    )
    assert saved["decision"] == "approval_required"
    assert saved["reason_code"] == "approval_required_external_commitment"
    assert saved["result"] == "pending_approval"
    assert saved["payload_digest"] == action.payload_digest
    assert "payload" not in saved


def test_runtime_kernel_audits_permission_denial_without_caller_metadata(tmp_path: Path):
    plugin_registry = _plugin_registry(
        plugin_id="records",
        capability="records.write",
        permissions=("records.write",),
    )
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
        plugin_registry=plugin_registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute",),
            handler=lambda context: None,
        )
    )
    sentinel = "PRIVATE-AUDIT-METADATA-d81b"
    action = PlannedAction(
        action_id="action-denied",
        plugin_id="records",
        capability="records.write",
        authority=ActionAuthority.AUTONOMOUS,
        reversible=True,
        external_effect=False,
        affects_commitment=False,
        risk="low",
        payload_digest="c" * 64,
        operation=sentinel,
        resource=sentinel,
    )

    decision = kernel.authorize_action(
        "body_agent",
        action,
        correlation_id="corr-denied",
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert decision.reason_code == "agent_permission_denied"
    audit_text = (tmp_path / "runtime_state" / "audit.jsonl").read_text(
        encoding="utf-8"
    )
    saved = json.loads(audit_text)
    assert saved["result"] == "suggested"
    assert saved["reason_code"] == "agent_permission_denied"
    assert sentinel not in audit_text


def test_runtime_kernel_requires_registered_provider_for_action_authorization(tmp_path: Path):
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "records.write"),
            handler=lambda context: None,
        )
    )
    action = PlannedAction(
        action_id="action-no-registry",
        plugin_id="records",
        capability="records.write",
        authority=ActionAuthority.AUTONOMOUS,
        reversible=True,
        external_effect=False,
        affects_commitment=False,
        risk="low",
        payload_digest="d" * 64,
    )

    with pytest.raises(RuntimeError, match="plugin_registry_required"):
        kernel.authorize_action(
            "body_agent",
            action,
            correlation_id="corr-no-registry",
        )

    assert not (tmp_path / "runtime_state" / "audit.jsonl").exists()


def test_runtime_event_audit_redacts_task_body_but_execution_still_receives_it(tmp_path: Path):
    kernel = RuntimeKernel(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    sentinel = "PRIVATE-TASK-BODY-a18d"
    received: list[str] = []
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: received.append(context.task) or "ok",
        )
    )
    kernel.activate_agent("body_agent")

    kernel.execute("body_agent", credential=BODY_CREDENTIAL, task=sentinel)

    assert received == [sentinel]
    event_log = (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8")
    assert sentinel not in event_log
    assert sentinel not in json.dumps(kernel.events.history, ensure_ascii=False)
