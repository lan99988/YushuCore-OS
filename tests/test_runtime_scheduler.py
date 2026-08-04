from __future__ import annotations

import json
from pathlib import Path

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


def _kernel(tmp_path: Path, *, policy: RuntimePolicy | None = None) -> RuntimeKernel:
    gateway = _gateway(tmp_path)
    if policy is not None:
        return RuntimeKernel.from_policy(
            gateway=gateway,
            state_path=tmp_path / "runtime_state",
            policy=policy,
        )
    return RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )


def test_runtime_policy_loads_retry_settings(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "network.yaml").write_text("network_mode: OFF\n", encoding="utf-8")
    (config_dir / "model.yaml").write_text(
        "local_model: qwen3:8b\ncloud_model: deepseek-reasoner\n",
        encoding="utf-8",
    )
    (config_dir / "runtime.yaml").write_text(
        "retry:\n  max_attempts: 3\n",
        encoding="utf-8",
    )

    policy = load_runtime_policy(config_dir)

    assert policy.retry.max_attempts == 3


def test_runtime_kernel_monitor_and_update_advance_scheduler_state(tmp_path: Path):
    kernel = _kernel(tmp_path)
    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=lambda context: "ok",
        )
    )
    kernel.activate_agent("body_agent")

    monitor = kernel.monitor_agent("body_agent", check=lambda agent: {"healthy": True})
    update = kernel.update_agent("body_agent", changes={"version": "1.1"})

    assert monitor.status == "monitored"
    assert monitor.details == {"healthy": True}
    assert update.status == "updated"
    assert update.details == {"version": "1.1"}
    assert kernel.scheduler.state("body_agent") == "updated"


def test_runtime_kernel_retries_failed_execution_by_policy(tmp_path: Path):
    policy = RuntimePolicy.with_retry(
        network_mode="OFF",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
        retry_max_attempts=3,
    )
    kernel = _kernel(tmp_path, policy=policy)
    attempts = {"count": 0}

    def flaky_handler(context):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return "recovered"

    kernel.register_agent(
        AgentDefinition(
            agent_id="body_agent",
            name="Body Runtime Agent",
            domain="body",
            autonomy_level=2,
            risk_level="medium",
            permissions=("execute", "read_knowledge"),
            handler=flaky_handler,
        )
    )
    kernel.activate_agent("body_agent")

    result = kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")

    assert result.output == "recovered"
    assert attempts["count"] == 3
    events = [
        json.loads(line)
        for line in (tmp_path / "runtime_state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    retry_events = [event for event in events if event["event"] == "agent_retry"]
    assert [event["attempt"] for event in retry_events] == [1, 2]
    assert events[-1]["event"] == "agent_completed"
    assert events[-1]["attempt"] == 3
