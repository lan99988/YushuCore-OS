import json
from pathlib import Path

import pytest

from knowledge_system.gateway import (
    ApprovalRequired,
    AgentPolicy,
    KnowledgeGateway,
    PermissionDenied,
    ProposalConflict,
)


def _write_note(root: Path, relative: str, *, node_id: str, domain: str, agent: str,
                status: str = "validated", sensitivity: str = "level_1",
                body: str = "睡眠改善学习效率") -> Path:
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
    _write_note(vault, "05_Domains/Body/sleep.md", node_id="KN-BODY-1", domain="body", agent="body_agent")
    _write_note(vault, "05_Domains/Study/sleep.md", node_id="KN-STUDY-1", domain="study", agent="study_agent")
    _write_note(vault, "05_Domains/Body/core.md", node_id="KN-CORE-1", domain="body", agent="body_agent", sensitivity="level_3")
    _write_note(vault, "05_Domains/Body/draft.md", node_id="KN-DRAFT-1", domain="body", agent="body_agent", status="candidate")
    return KnowledgeGateway(
        vault,
        state_path=tmp_path / "state",
        policies={
            "body_agent": AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity="level_2",
            ),
            "study_agent": AgentPolicy(
                allowed_folders=("05_Domains/Study",),
                allowed_domains=("study",),
                max_sensitivity="level_2",
            ),
        },
    )


def test_query_knowledge_applies_folder_metadata_policy_and_status(tmp_path: Path):
    gateway = _gateway(tmp_path)

    result = gateway.query_knowledge("睡眠", agent_id="body_agent")

    assert result.permission == "approved"
    assert [node.id for node in result.nodes] == ["KN-BODY-1"]
    assert result.denied_count >= 1


def test_get_context_returns_only_authorized_active_nodes(tmp_path: Path):
    gateway = _gateway(tmp_path)

    context = gateway.get_context("睡眠", agent_id="study_agent")

    assert [node.id for node in context.knowledge] == ["KN-STUDY-1"]
    assert context.principles == []


def test_request_update_is_durable_but_does_not_modify_vault_until_approval(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    before = target.read_text(encoding="utf-8")

    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    assert proposal.status == "pending"
    assert target.read_text(encoding="utf-8") == before
    assert (tmp_path / "state/proposals" / f"{proposal.proposal_id}.json").exists()


def test_approve_change_writes_only_after_human_review_and_creates_backup(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    approved = gateway.approve_change(proposal.proposal_id, reviewer="owner")

    assert approved.status == "approved"
    assert "稳定睡眠是学习效率的重要条件" in target.read_text(encoding="utf-8")
    assert (tmp_path / "state/backups" / f"{proposal.proposal_id}.md").exists()
    events = [
        json.loads(line)
        for line in (tmp_path / "state/audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["decision"] for event in events] == ["pending", "approved"]


def test_high_sensitivity_change_requires_explicit_core_approval(tmp_path: Path):
    gateway = _gateway(tmp_path)

    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-CORE-1",
        old="睡眠改善学习效率",
        new="我的核心健康原则",
        reason="原则提议",
        confidence=0.7,
        risk="high",
    )

    with pytest.raises(ApprovalRequired):
        gateway.approve_change(proposal.proposal_id, reviewer="owner")

    approved = gateway.approve_change(
        proposal.proposal_id,
        reviewer="owner",
        core_approval=True,
    )
    assert approved.status == "approved"


def test_approve_change_rejects_stale_target_and_never_overwrites_newer_content(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )
    target.write_text(target.read_text(encoding="utf-8").replace("睡眠改善学习效率", "人工已更新结论"), encoding="utf-8")

    with pytest.raises(ProposalConflict):
        gateway.approve_change(proposal.proposal_id, reviewer="owner")

    assert "人工已更新结论" in target.read_text(encoding="utf-8")


def test_gateway_rejects_unknown_target_instead_of_following_path_input(tmp_path: Path):
    gateway = _gateway(tmp_path)

    with pytest.raises(PermissionDenied):
        gateway.request_update(
            agent_id="body_agent",
            target_id="../outside.md",
            old="anything",
            new="changed",
            reason="path escape attempt",
            confidence=0.5,
            risk="medium",
        )

    events = [
        json.loads(line)
        for line in (tmp_path / "state/audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["decision"] == "denied"
    assert events[-1]["reason"] == "unknown_target"


def test_reject_change_records_human_decision_without_modifying_vault(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    before = target.read_text(encoding="utf-8")
    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    rejected = gateway.reject_change(
        proposal.proposal_id,
        reviewer="owner",
        reason="证据不足",
    )

    assert rejected.status == "rejected"
    assert rejected.reviewer == "owner"
    assert target.read_text(encoding="utf-8") == before
    assert not (tmp_path / "state/backups" / f"{proposal.proposal_id}.md").exists()
    events = [
        json.loads(line)
        for line in (tmp_path / "state/audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["decision"] == "rejected"
    assert events[-1]["reason"] == "证据不足"


def test_expire_change_closes_pending_proposal_without_touching_vault(tmp_path: Path):
    gateway = _gateway(tmp_path)
    proposal = gateway.request_update(
        agent_id="body_agent",
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    expired = gateway.expire_change(proposal.proposal_id, reason="超过审核窗口")

    assert expired.status == "expired"
    assert "睡眠改善学习效率" in (tmp_path / "vault/05_Domains/Body/sleep.md").read_text(encoding="utf-8")
