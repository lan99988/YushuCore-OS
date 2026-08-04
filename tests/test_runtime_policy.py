from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_system.gateway import AgentPolicy, KnowledgeGateway, ReviewerPolicy
from runtime_core import AgentDefinition, RuntimeKernel, RuntimePolicy, load_runtime_policy


BODY_CREDENTIAL = "body-secret"
OWNER_CREDENTIAL = "owner-secret"


def _write_note(root: Path) -> None:
    path = root / "05_Domains/Body/sleep.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
id: KN-BODY-1
type: knowledge
title: KN-BODY-1
domain: body
layer: knowledge
source: manual
author: owner
created: 2026-08-04
updated: 2026-08-04
status: validated
confidence: 0.85
agent_access:
  - body_agent
sensitivity: level_1
version: "1.0"
relations: []
---
# KN-BODY-1

sleep improves learning efficiency
""",
        encoding="utf-8",
    )


def _gateway(tmp_path: Path) -> KnowledgeGateway:
    vault = tmp_path / "vault"
    _write_note(vault)
    return KnowledgeGateway(
        vault,
        state_path=tmp_path / "gateway_state",
        policies={
            "body_agent": AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity="level_2",
            ),
        },
        agent_credentials={"body_agent": BODY_CREDENTIAL},
        reviewers={"owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True)},
    )


def test_runtime_policy_loads_network_and_model_yaml(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "network.yaml").write_text("network_mode: OFF\n", encoding="utf-8")
    (config_dir / "model.yaml").write_text(
        """local_model: qwen3:8b
cloud_model: deepseek-reasoner
""",
        encoding="utf-8",
    )

    policy = load_runtime_policy(config_dir)

    assert policy == RuntimePolicy(
        network_mode="OFF",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    assert policy.model_router().select(complexity="deep", network_mode=policy.network_mode).provider == "local"


def test_runtime_policy_rejects_default_network_modes_that_are_not_frozen():
    with pytest.raises(ValueError, match="network_mode"):
        RuntimePolicy(
            network_mode="ONLINE",
            local_model="qwen3:8b",
            cloud_model="deepseek-reasoner",
        )


def test_runtime_kernel_from_policy_uses_off_as_default_network_mode(tmp_path: Path):
    policy = RuntimePolicy(
        network_mode="OFF",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    kernel = RuntimeKernel.from_policy(
        gateway=_gateway(tmp_path),
        state_path=tmp_path / "runtime_state",
        policy=policy,
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
    kernel.activate_agent("body_agent")

    result = kernel.execute(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="sleep",
        complexity="deep",
    )

    assert result.output == "local"
