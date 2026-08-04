from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_system.gateway import (
    AgentPolicy,
    KnowledgeGateway,
    ReviewerPolicy,
)
from runtime_core import (
    AgentDefinition,
    AgentLifecycleError,
    ModelRouter,
    PermissionDenied,
    RuntimeKernel,
)


BODY_CREDENTIAL = "body-secret"
STUDY_CREDENTIAL = "study-secret"
OWNER_CREDENTIAL = "owner-secret"


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


def _gateway(tmp_path: Path) -> KnowledgeGateway:
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
                max_sensitivity="level_2",
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
        "agent_started",
        "agent_completed",
    ]
    assert events[0]["agent_id"] == "body_agent"
    assert events[2]["model"]["provider"] == "local"


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


def test_model_router_uses_local_first_and_cloud_for_complex_tasks():
    router = ModelRouter(local_model="qwen3:8b", cloud_model="deepseek-reasoner")

    local_route = router.select(complexity="standard", network_mode="OFF")
    cloud_route = router.select(complexity="deep", network_mode="ASSIST")

    assert local_route.provider == "local"
    assert local_route.model_name == "qwen3:8b"
    assert cloud_route.provider == "cloud"
    assert cloud_route.model_name == "deepseek-reasoner"
