from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from knowledge_system.gateway.models import (
    AgentPolicy,
    ContextResponse,
    GatewayNode,
    Proposal,
    QueryResponse,
    ReviewerPolicy,
)
from knowledge_system.gateway.permissions import (
    SENSITIVITY_RANK,
    check_proposal_permission,
    check_read_permission,
)
from knowledge_system.gateway.proposals import JsonProposalStore, LockUnavailable
from knowledge_system.gateway.repository import MarkdownVaultRepository


class PermissionDenied(RuntimeError):
    pass


class ApprovalRequired(PermissionDenied):
    pass


class ProposalConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class KnowledgeGateway:
    def __init__(
        self,
        vault_path: str | Path,
        *,
        state_path: str | Path,
        policies: dict[str, AgentPolicy],
        agent_credentials: dict[str, str],
        reviewers: dict[str, ReviewerPolicy],
    ) -> None:
        self.repository = MarkdownVaultRepository(vault_path)
        state_root = Path(state_path).resolve()
        try:
            state_root.relative_to(self.repository.root)
        except ValueError:
            pass
        else:
            raise ValueError("state_path must be outside the Knowledge Vault")
        self.store = JsonProposalStore(state_root)
        self.policies = dict(policies)
        if set(self.policies) != set(agent_credentials):
            raise ValueError("every Agent policy must have exactly one credential")
        for agent_id, credential in agent_credentials.items():
            if not credential.strip():
                raise ValueError(f"Agent credential cannot be empty: {agent_id}")
        for reviewer, policy in reviewers.items():
            if not policy.credential.strip():
                raise ValueError(f"Reviewer credential cannot be empty: {reviewer}")
        self._agent_credentials = {
            agent_id: _digest(credential) for agent_id, credential in agent_credentials.items()
        }
        self._reviewers = {
            reviewer: (_digest(policy.credential), policy.can_approve_core)
            for reviewer, policy in reviewers.items()
        }
        self._recover_transactions()

    def _recover_transactions(self) -> None:
        for transaction in self.store.transactions():
            proposal_id = transaction["proposal_id"]
            proposal = self.store.load(proposal_id)
            target = (self.repository.root / Path(transaction["target_path"])).resolve()
            target.relative_to(self.repository.root)
            if proposal.status == "pending":
                backup = self.store.backups_path / f"{proposal_id}.md"
                original = backup.read_text(encoding="utf-8")
                if _digest(original) != transaction["original_digest"]:
                    raise ProposalConflict("transaction backup digest mismatch")
                rollback = target.with_name(f".{target.name}.{proposal_id}.recovery")
                rollback.write_text(original, encoding="utf-8")
                os.replace(rollback, target)
                self.store.audit(
                    {"action": "startup_recovery", "agent": proposal.agent,
                     "proposal_id": proposal_id, "resource": proposal.target_id,
                     "decision": "rolled_back", "timestamp": _now()}
                )
            elif proposal.status == "approved":
                if _digest(target.read_text(encoding="utf-8")) != transaction["updated_digest"]:
                    raise ProposalConflict("approved transaction target digest mismatch")
                self.store.audit(
                    {"action": "startup_recovery", "agent": proposal.agent,
                     "proposal_id": proposal_id, "resource": proposal.target_id,
                     "decision": "approved_recovered", "timestamp": _now()}
                )
            else:
                raise ProposalConflict("transaction has an invalid proposal status")
            self.store.clear_transaction(proposal_id)

    def _audit_denied(
        self,
        action: str,
        *,
        reason: str,
        agent: str | None = None,
        reviewer: str | None = None,
        resource: str | None = None,
    ) -> None:
        event = {"action": action, "decision": "denied", "reason": reason, "timestamp": _now()}
        if agent is not None:
            event["agent"] = agent
        if reviewer is not None:
            event["reviewer"] = reviewer
        if resource is not None:
            event["resource"] = resource
        self.store.audit(event)

    def _policy(self, agent_id: str, credential: str) -> AgentPolicy:
        if not credential.strip():
            self.store.audit(
                {"action": "permission_check", "agent": agent_id,
                 "decision": "denied", "reason": "empty_agent_credential", "timestamp": _now()}
            )
            raise PermissionDenied("empty_agent_credential")
        try:
            policy = self.policies[agent_id]
            expected = self._agent_credentials[agent_id]
        except KeyError as exc:
            self.store.audit(
                {"action": "permission_check", "agent": agent_id,
                 "decision": "denied", "reason": "unregistered_agent", "timestamp": _now()}
            )
            raise PermissionDenied("unregistered_agent") from exc
        if not hmac.compare_digest(expected, _digest(credential)):
            self.store.audit(
                {"action": "permission_check", "agent": agent_id,
                 "decision": "denied", "reason": "invalid_agent_credential", "timestamp": _now()}
            )
            raise PermissionDenied("invalid_agent_credential")
        return policy

    def _reviewer(self, reviewer: str, credential: str) -> bool:
        if not credential.strip():
            self.store.audit(
                {"action": "approval_identity", "reviewer": reviewer,
                 "decision": "denied", "reason": "empty_reviewer_credential", "timestamp": _now()}
            )
            raise ApprovalRequired("empty_reviewer_credential")
        try:
            expected, can_approve_core = self._reviewers[reviewer]
        except KeyError as exc:
            self.store.audit(
                {"action": "approval_identity", "reviewer": reviewer,
                 "decision": "denied", "reason": "unregistered_reviewer", "timestamp": _now()}
            )
            raise ApprovalRequired("unregistered_reviewer") from exc
        if not hmac.compare_digest(expected, _digest(credential)):
            self.store.audit(
                {"action": "approval_identity", "reviewer": reviewer,
                 "decision": "denied", "reason": "invalid_reviewer_credential", "timestamp": _now()}
            )
            raise ApprovalRequired("invalid_reviewer_credential")
        return can_approve_core

    @staticmethod
    def _matches(node: GatewayNode, query: str) -> bool:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return True
        haystack = " ".join((node.title, node.body, " ".join(node.domain))).casefold()
        return all(term in haystack for term in terms)

    def query_knowledge(self, query: str, *, agent_id: str, credential: str) -> QueryResponse:
        policy = self._policy(agent_id, credential)
        scan = self.repository.scan()
        allowed: list[GatewayNode] = []
        denied_count = 0
        for node in scan.nodes:
            decision = check_read_permission(node, agent_id, policy)
            if not decision.allowed:
                denied_count += 1
                continue
            if self._matches(node, query):
                allowed.append(node)
        self.store.audit(
            {"action": "query_knowledge", "agent": agent_id, "decision": "approved",
             "result_count": len(allowed), "denied_count": denied_count, "timestamp": _now()}
        )
        return QueryResponse(allowed, "approved", denied_count, scan.invalid_count)

    def get_context(self, task: str, *, agent_id: str, credential: str) -> ContextResponse:
        nodes = self.query_knowledge(task, agent_id=agent_id, credential=credential).nodes
        return ContextResponse(
            knowledge=[node for node in nodes if node.type not in {"experience", "principle"}],
            experience=[node for node in nodes if node.type == "experience"],
            principles=[node for node in nodes if node.type == "principle"],
        )

    def request_update(
        self,
        *,
        agent_id: str,
        credential: str,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
    ) -> Proposal:
        policy = self._policy(agent_id, credential)
        node = self.repository.find_by_id(target_id)
        if node is None:
            self.store.audit(
                {"action": "request_update", "agent": agent_id, "resource": target_id,
                 "decision": "denied", "reason": "unknown_target", "timestamp": _now()}
            )
            raise PermissionDenied("unknown_target")
        decision = check_proposal_permission(node, agent_id, policy)
        if not decision.allowed:
            self.store.audit(
                {"action": "request_update", "agent": agent_id, "resource": target_id,
                 "decision": "denied", "reason": decision.reason, "timestamp": _now()}
            )
            raise PermissionDenied(decision.reason)
        if not old or not new or old == new or not reason.strip():
            self._audit_denied(
                "request_update", agent=agent_id, resource=target_id, reason="invalid_change"
            )
            raise ProposalConflict("proposal must replace non-empty content")
        if not 0.0 <= confidence <= 1.0:
            self._audit_denied(
                "request_update", agent=agent_id, resource=target_id, reason="invalid_confidence"
            )
            raise ValueError("confidence must be between 0 and 1")
        if risk not in {"low", "medium", "high"}:
            self._audit_denied(
                "request_update", agent=agent_id, resource=target_id, reason="invalid_risk"
            )
            raise ValueError("risk must be low, medium, or high")

        target = self.repository.resolve_node_path(node)
        content = target.read_text(encoding="utf-8")
        if content.count(old) != 1:
            self._audit_denied(
                "request_update", agent=agent_id, resource=target_id, reason="old_content_conflict"
            )
            raise ProposalConflict("old content must occur exactly once")
        proposal = Proposal(
            proposal_id=uuid4().hex,
            agent=agent_id,
            target_id=target_id,
            target_path=node.path,
            target_digest=_digest(content),
            old=old,
            new=new,
            reason=reason,
            confidence=confidence,
            risk=risk,
            status="pending",
            requires_core_approval=(risk == "high" or SENSITIVITY_RANK[node.sensitivity] >= 3),
            created=_now(),
        )
        self.store.save(proposal)
        try:
            self.store.audit(
                {"action": "request_update", "agent": agent_id,
                 "proposal_id": proposal.proposal_id, "resource": target_id,
                 "decision": "pending", "reason": reason, "confidence": confidence,
                 "risk": risk, "timestamp": proposal.created}
            )
        except Exception:
            self.store.delete(proposal.proposal_id)
            raise
        return proposal

    def approve_change(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reviewer_credential: str,
    ) -> Proposal:
        can_approve_core = self._reviewer(reviewer, reviewer_credential)
        try:
            with self.store.approval_lock():
                return self._approve_change_locked(
                    proposal_id,
                    reviewer=reviewer,
                    can_approve_core=can_approve_core,
                )
        except LockUnavailable as exc:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="approval_in_progress"
            )
            raise ProposalConflict("approval_in_progress") from exc

    def _approve_change_locked(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        can_approve_core: bool,
    ) -> Proposal:
        proposal = self.store.load(proposal_id)
        if reviewer == proposal.agent:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="separation_of_duties"
            )
            raise ApprovalRequired("separation_of_duties")
        if proposal.status != "pending":
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="proposal_not_pending"
            )
            raise ProposalConflict("proposal is not pending")
        if proposal.requires_core_approval and not can_approve_core:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="core_approval_required"
            )
            raise ApprovalRequired("core approval is required")

        node = self.repository.find_by_id(proposal.target_id)
        if node is None or node.path != proposal.target_path:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="target_missing"
            )
            raise ProposalConflict("proposal target no longer exists")
        target = self.repository.resolve_node_path(node)
        content = target.read_text(encoding="utf-8")
        if _digest(content) != proposal.target_digest or content.count(proposal.old) != 1:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="target_changed"
            )
            raise ProposalConflict("proposal target changed after request")

        updated_content = content.replace(proposal.old, proposal.new, 1)
        try:
            self.repository.validate_replacement(node, updated_content)
        except ValueError as exc:
            self._audit_denied(
                "approve_change", reviewer=reviewer, resource=proposal_id,
                reason="replacement_validation_failed"
            )
            raise ProposalConflict("replacement validation failed") from exc

        self.store.backup(proposal, content)
        self.store.start_transaction(proposal, content)
        temporary = target.with_name(f".{target.name}.{proposal.proposal_id}.tmp")
        temporary.write_text(updated_content, encoding="utf-8")
        approved = replace(proposal, status="approved", reviewer=reviewer, review_time=_now())
        try:
            os.replace(temporary, target)
            self.store.save(approved)
            self.store.audit(
                {"action": "approve_change", "agent": proposal.agent, "approved_by": reviewer,
                 "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
                 "decision": "approved", "timestamp": approved.review_time}
            )
            self.store.clear_transaction(proposal.proposal_id)
        except Exception:
            rollback = target.with_name(f".{target.name}.{proposal.proposal_id}.rollback")
            rollback.write_text(content, encoding="utf-8")
            os.replace(rollback, target)
            self.store.save(proposal)
            self.store.audit(
                {"action": "approve_change_rollback", "agent": proposal.agent,
                 "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
                 "decision": "rolled_back", "timestamp": _now()}
            )
            self.store.clear_transaction(proposal.proposal_id)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return approved

    def reject_change(
        self, proposal_id: str, *, reviewer: str, reviewer_credential: str, reason: str
    ) -> Proposal:
        self._reviewer(reviewer, reviewer_credential)
        if not reason.strip():
            raise ValueError("rejection reason is required")
        proposal = self.store.load(proposal_id)
        if reviewer == proposal.agent:
            self._audit_denied(
                "reject_change", reviewer=reviewer, resource=proposal_id,
                reason="separation_of_duties"
            )
            raise ApprovalRequired("separation_of_duties")
        if proposal.status != "pending":
            self._audit_denied(
                "reject_change", reviewer=reviewer, resource=proposal_id,
                reason="proposal_not_pending"
            )
            raise ProposalConflict("proposal is not pending")
        rejected = replace(proposal, status="rejected", reviewer=reviewer, review_time=_now())
        self.store.save(rejected)
        try:
            self.store.audit(
                {"action": "reject_change", "agent": proposal.agent, "approved_by": reviewer,
                 "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
                 "decision": "rejected", "reason": reason, "timestamp": rejected.review_time}
            )
        except Exception:
            self.store.save(proposal)
            raise
        return rejected

    def expire_change(
        self, proposal_id: str, *, reviewer: str, reviewer_credential: str, reason: str
    ) -> Proposal:
        self._reviewer(reviewer, reviewer_credential)
        if not reason.strip():
            raise ValueError("expiration reason is required")
        proposal = self.store.load(proposal_id)
        if reviewer == proposal.agent:
            self._audit_denied(
                "expire_change", reviewer=reviewer, resource=proposal_id,
                reason="separation_of_duties"
            )
            raise ApprovalRequired("separation_of_duties")
        if proposal.status != "pending":
            self._audit_denied(
                "expire_change", reviewer=reviewer, resource=proposal_id,
                reason="proposal_not_pending"
            )
            raise ProposalConflict("proposal is not pending")
        expired = replace(proposal, status="expired", reviewer=reviewer, review_time=_now())
        self.store.save(expired)
        try:
            self.store.audit(
                {"action": "expire_change", "agent": proposal.agent,
                 "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
                 "decision": "expired", "reason": reason, "timestamp": expired.review_time}
            )
        except Exception:
            self.store.save(proposal)
            raise
        return expired
