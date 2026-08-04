from __future__ import annotations

from pathlib import Path

from knowledge_system.gateway import AgentPolicy, KnowledgeGateway, ReviewerPolicy
from runtime_core import AgentDefinition, KnowledgeGatewayClient, RuntimeKernel


BODY_CREDENTIAL = "body-secret"
OWNER_CREDENTIAL = "owner-secret"


def _write_note(root: Path, *, sensitivity: str = "level_1") -> None:
    path = root / "05_Domains/Body/sleep.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
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
sensitivity: {sensitivity}
version: "1.0"
relations: []
---
# KN-BODY-1

sleep improves learning efficiency
""",
        encoding="utf-8",
    )


def _gateway(tmp_path: Path, *, sensitivity: str = "level_1") -> KnowledgeGateway:
    vault = tmp_path / "vault"
    _write_note(vault, sensitivity=sensitivity)
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
        },
        agent_credentials={"body_agent": BODY_CREDENTIAL},
        reviewers={"owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True)},
    )


class SpyGatewayClient(KnowledgeGatewayClient):
    def __init__(self, gateway):
        super().__init__(gateway)
        self.calls: list[str] = []

    def get_context(self, *args, **kwargs):
        self.calls.append("get_context")
        return super().get_context(*args, **kwargs)

    def request_update(self, *args, **kwargs):
        self.calls.append("request_update")
        return super().request_update(*args, **kwargs)

    def get_context_with_access_grant(self, *args, **kwargs):
        self.calls.append("get_context_with_access_grant")
        return super().get_context_with_access_grant(*args, **kwargs)


def test_runtime_kernel_uses_gateway_client_for_context_and_proposals(tmp_path: Path):
    client = SpyGatewayClient(_gateway(tmp_path))
    kernel = RuntimeKernel(
        gateway_client=client,
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
            handler=lambda context: [node.id for node in context.knowledge],
        )
    )
    kernel.activate_agent("body_agent")

    result = kernel.execute("body_agent", credential=BODY_CREDENTIAL, task="sleep")
    proposal = kernel.request_update(
        "body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="sleep improves learning efficiency",
        new="sleep and recovery improve learning efficiency",
        reason="update through gateway client",
        confidence=0.8,
        risk="medium",
    )

    assert result.output == ["KN-BODY-1"]
    assert proposal.status == "pending"
    assert client.calls == ["get_context", "request_update"]
    assert kernel.gateway_client is client


def test_runtime_access_grant_uses_gateway_client(tmp_path: Path):
    client = SpyGatewayClient(_gateway(tmp_path, sensitivity="level_3"))
    kernel = RuntimeKernel(
        gateway_client=client,
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
        resource="05_Domains/Body/sleep.md",
        reason="Need approved high-sensitivity context.",
        sensitivity="level_3",
    )
    approved = kernel.approve_access_request(
        request.request_id,
        reviewer="owner",
        reason="Approved for one task.",
    )

    context = kernel.get_context_with_access(
        "body_agent",
        credential=BODY_CREDENTIAL,
        task="sleep",
        access_request_id=approved.request_id,
    )

    assert [node.id for node in context.knowledge] == ["KN-BODY-1"]
    assert client.calls == ["get_context_with_access_grant"]
