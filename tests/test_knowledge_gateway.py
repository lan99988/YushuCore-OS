import json
from pathlib import Path

import pytest

from knowledge_system.gateway import (
    ApprovalRequired,
    AgentPolicy,
    KnowledgeGateway,
    PermissionDenied,
    ProposalConflict,
    ReviewerPolicy,
)


BODY_CREDENTIAL = "body-secret"
STUDY_CREDENTIAL = "study-secret"
OWNER_CREDENTIAL = "owner-secret"
REVIEWER_CREDENTIAL = "reviewer-secret"


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
            "reviewer": ReviewerPolicy(credential=REVIEWER_CREDENTIAL, can_approve_core=False),
            "body_agent": ReviewerPolicy(credential="agent-review-secret", can_approve_core=True),
        },
    )


def test_query_knowledge_applies_folder_metadata_policy_and_status(tmp_path: Path):
    gateway = _gateway(tmp_path)

    result = gateway.query_knowledge("睡眠", agent_id="body_agent", credential=BODY_CREDENTIAL)

    assert result.permission == "approved"
    assert [node.id for node in result.nodes] == ["KN-BODY-1"]
    assert result.denied_count >= 1


def test_get_context_returns_only_authorized_active_nodes(tmp_path: Path):
    gateway = _gateway(tmp_path)

    context = gateway.get_context("睡眠", agent_id="study_agent", credential=STUDY_CREDENTIAL)

    assert [node.id for node in context.knowledge] == ["KN-STUDY-1"]
    assert context.principles == []


def test_access_grant_context_is_limited_to_single_resource_path(tmp_path: Path):
    gateway = _gateway(tmp_path)
    _write_note(
        tmp_path / "vault",
        "05_Domains/Body/other-core.md",
        node_id="KN-CORE-2",
        domain="body",
        agent="body_agent",
        sensitivity="level_3",
    )

    normal_context = gateway.get_context(
        "鐫＄湢",
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
    )
    assert "KN-CORE-1" not in [node.id for node in normal_context.knowledge]
    assert "KN-CORE-2" not in [node.id for node in normal_context.knowledge]

    granted_context = gateway.get_context_with_access_grant(
        "鐫＄湢",
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        resource_path="05_Domains/Body/core.md",
        max_sensitivity="level_3",
    )

    assert [node.id for node in granted_context.knowledge] == ["KN-CORE-1"]


def test_request_update_is_durable_but_does_not_modify_vault_until_approval(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    before = target.read_text(encoding="utf-8")

    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
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
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    approved = gateway.approve_change(
        proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
    )

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
        credential=BODY_CREDENTIAL,
        target_id="KN-CORE-1",
        old="睡眠改善学习效率",
        new="我的核心健康原则",
        reason="原则提议",
        confidence=0.7,
        risk="high",
    )

    with pytest.raises(ApprovalRequired):
        gateway.approve_change(
            proposal.proposal_id,
            reviewer="reviewer",
            reviewer_credential=REVIEWER_CREDENTIAL,
        )

    approved = gateway.approve_change(
        proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
    )
    assert approved.status == "approved"


def test_approve_change_rejects_stale_target_and_never_overwrites_newer_content(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )
    target.write_text(target.read_text(encoding="utf-8").replace("睡眠改善学习效率", "人工已更新结论"), encoding="utf-8")

    with pytest.raises(ProposalConflict):
        gateway.approve_change(
            proposal.proposal_id,
            reviewer="owner",
            reviewer_credential=OWNER_CREDENTIAL,
        )

    assert "人工已更新结论" in target.read_text(encoding="utf-8")


def test_gateway_rejects_unknown_target_instead_of_following_path_input(tmp_path: Path):
    gateway = _gateway(tmp_path)

    with pytest.raises(PermissionDenied):
        gateway.request_update(
            agent_id="body_agent",
            credential=BODY_CREDENTIAL,
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
        credential=BODY_CREDENTIAL,
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
        reviewer_credential=OWNER_CREDENTIAL,
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
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    expired = gateway.expire_change(
        proposal.proposal_id,
        reviewer="owner",
        reviewer_credential=OWNER_CREDENTIAL,
        reason="超过审核窗口",
    )

    assert expired.status == "expired"
    assert "睡眠改善学习效率" in (tmp_path / "vault/05_Domains/Body/sleep.md").read_text(encoding="utf-8")


def test_approval_rolls_back_vault_if_post_write_audit_fails(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    before = target.read_text(encoding="utf-8")
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )
    original_audit = gateway.store.audit

    def fail_after_write(event):
        if event["action"] == "approve_change":
            raise OSError("audit unavailable")
        original_audit(event)

    gateway.store.audit = fail_after_write

    with pytest.raises(OSError, match="audit unavailable"):
        gateway.approve_change(
            proposal.proposal_id,
            reviewer="owner",
            reviewer_credential=OWNER_CREDENTIAL,
        )

    assert target.read_text(encoding="utf-8") == before
    assert gateway.store.load(proposal.proposal_id).status == "pending"


def test_agent_identity_cannot_be_impersonated_with_only_agent_id(tmp_path: Path):
    gateway = _gateway(tmp_path)

    with pytest.raises(PermissionDenied, match="invalid_agent_credential"):
        gateway.query_knowledge(
            "睡眠",
            agent_id="body_agent",
            credential="wrong-secret",
        )


def test_agent_cannot_approve_its_own_proposal_even_with_reviewer_credential(tmp_path: Path):
    gateway = _gateway(tmp_path)
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    with pytest.raises(ApprovalRequired, match="separation_of_duties"):
        gateway.approve_change(
            proposal.proposal_id,
            reviewer="body_agent",
            reviewer_credential="agent-review-secret",
        )


def test_state_path_cannot_be_inside_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="state_path must be outside"):
        KnowledgeGateway(
            vault,
            state_path=vault / "99_System/runtime",
            policies={},
            agent_credentials={},
            reviewers={},
        )


def test_duplicate_node_ids_are_quarantined_from_query_results(tmp_path: Path):
    gateway = _gateway(tmp_path)
    _write_note(
        tmp_path / "vault",
        "05_Domains/Body/duplicate.md",
        node_id="KN-BODY-1",
        domain="body",
        agent="body_agent",
    )

    result = gateway.query_knowledge(
        "睡眠",
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
    )

    assert all(node.id != "KN-BODY-1" for node in result.nodes)
    assert result.invalid_count >= 2


def test_approval_revalidates_resulting_markdown_before_write(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    before = target.read_text(encoding="utf-8")
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="status: validated",
        new="status: invalid",
        reason="非法状态测试",
        confidence=0.8,
        risk="medium",
    )

    with pytest.raises(ProposalConflict, match="validation"):
        gateway.approve_change(
            proposal.proposal_id,
            reviewer="owner",
            reviewer_credential=OWNER_CREDENTIAL,
        )

    assert target.read_text(encoding="utf-8") == before
    assert gateway.store.load(proposal.proposal_id).status == "pending"


def test_approval_lock_prevents_concurrent_change_application(tmp_path: Path):
    gateway = _gateway(tmp_path)
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="新的个人经验",
        confidence=0.8,
        risk="medium",
    )

    with gateway.store.approval_lock():
        with pytest.raises(ProposalConflict, match="approval_in_progress"):
            gateway.approve_change(
                proposal.proposal_id,
                reviewer="owner",
                reviewer_credential=OWNER_CREDENTIAL,
            )


def test_invalid_proposal_is_denied_and_audited(tmp_path: Path):
    gateway = _gateway(tmp_path)

    with pytest.raises(ProposalConflict):
        gateway.request_update(
            agent_id="body_agent",
            credential=BODY_CREDENTIAL,
            target_id="KN-BODY-1",
            old="",
            new="changed",
            reason="invalid",
            confidence=0.5,
            risk="medium",
        )

    events = [
        json.loads(line)
        for line in (tmp_path / "state/audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["decision"] == "denied"
    assert events[-1]["reason"] == "invalid_change"


def test_gateway_recovers_prepared_transaction_after_process_restart(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    original = target.read_text(encoding="utf-8")
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old="睡眠改善学习效率",
        new="稳定睡眠是学习效率的重要条件",
        reason="模拟进程中断",
        confidence=0.8,
        risk="medium",
    )
    gateway.store.backup(proposal, original)
    gateway.store.start_transaction(proposal, original)
    target.write_text(original.replace(proposal.old, proposal.new, 1), encoding="utf-8")

    restarted = KnowledgeGateway(
        tmp_path / "vault",
        state_path=tmp_path / "state",
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

    assert target.read_text(encoding="utf-8") == original
    assert restarted.store.load(proposal.proposal_id).status == "pending"
    assert list((tmp_path / "state/transactions").glob("*.json")) == []


def test_request_update_removes_orphan_proposal_if_audit_fails(tmp_path: Path):
    gateway = _gateway(tmp_path)

    def fail_audit(event):
        raise OSError("audit unavailable")

    gateway.store.audit = fail_audit

    with pytest.raises(OSError, match="audit unavailable"):
        gateway.request_update(
            agent_id="body_agent",
            credential=BODY_CREDENTIAL,
            target_id="KN-BODY-1",
            old="睡眠改善学习效率",
            new="稳定睡眠是学习效率的重要条件",
            reason="新的个人经验",
            confidence=0.8,
            risk="medium",
        )

    assert list((tmp_path / "state/proposals").glob("*.json")) == []


def test_sensitive_node_requires_explicit_proposal_sensitivity_grant(tmp_path: Path):
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "05_Domains/Body/core.md",
        node_id="KN-CORE-STRICT",
        domain="body",
        agent="body_agent",
        sensitivity="level_3",
    )
    gateway = KnowledgeGateway(
        vault,
        state_path=tmp_path / "state",
        policies={
            "body_agent": AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
        },
        agent_credentials={"body_agent": BODY_CREDENTIAL},
        reviewers={"owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True)},
    )

    with pytest.raises(PermissionDenied, match="proposal_sensitivity_denied"):
        gateway.request_update(
            agent_id="body_agent",
            credential=BODY_CREDENTIAL,
            target_id="KN-CORE-STRICT",
            old="鐫＄湢鏀瑰杽瀛︿範鏁堢巼",
            new="stable sleep improves learning efficiency",
            reason="sensitivity boundary test",
            confidence=0.8,
            risk="high",
        )


def test_gateway_rejects_empty_registered_credentials(tmp_path: Path):
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "05_Domains/Body/sleep.md",
        node_id="KN-BODY-1",
        domain="body",
        agent="body_agent",
    )
    policies = {
        "body_agent": AgentPolicy(
            allowed_folders=("05_Domains/Body",),
            allowed_domains=("body",),
            max_sensitivity="level_2",
        ),
    }

    with pytest.raises(ValueError, match="Agent credential cannot be empty"):
        KnowledgeGateway(
            vault,
            state_path=tmp_path / "agent-state",
            policies=policies,
            agent_credentials={"body_agent": ""},
            reviewers={"owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True)},
        )

    with pytest.raises(ValueError, match="Reviewer credential cannot be empty"):
        KnowledgeGateway(
            vault,
            state_path=tmp_path / "reviewer-state",
            policies=policies,
            agent_credentials={"body_agent": BODY_CREDENTIAL},
            reviewers={"owner": ReviewerPolicy(credential="", can_approve_core=True)},
        )


def test_reject_and_expire_self_review_attempts_are_audited(tmp_path: Path):
    gateway = _gateway(tmp_path)
    target = tmp_path / "vault/05_Domains/Body/sleep.md"
    old_body = [line for line in target.read_text(encoding="utf-8").splitlines() if line][-1]
    proposal = gateway.request_update(
        agent_id="body_agent",
        credential=BODY_CREDENTIAL,
        target_id="KN-BODY-1",
        old=old_body,
        new="stable sleep improves learning efficiency",
        reason="separation audit test",
        confidence=0.8,
        risk="medium",
    )

    with pytest.raises(ApprovalRequired, match="separation_of_duties"):
        gateway.reject_change(
            proposal.proposal_id,
            reviewer="body_agent",
            reviewer_credential="agent-review-secret",
            reason="self reject",
        )

    with pytest.raises(ApprovalRequired, match="separation_of_duties"):
        gateway.expire_change(
            proposal.proposal_id,
            reviewer="body_agent",
            reviewer_credential="agent-review-secret",
            reason="self expire",
        )

    events = [
        json.loads(line)
        for line in (tmp_path / "state/audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["action"] for event in events[-2:]] == ["reject_change", "expire_change"]
    assert all(event["decision"] == "denied" for event in events[-2:])
    assert all(event["reason"] == "separation_of_duties" for event in events[-2:])
