from __future__ import annotations

import hashlib
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
)
from knowledge_system.gateway.permissions import (
    SENSITIVITY_RANK,
    check_proposal_permission,
    check_read_permission,
)
from knowledge_system.gateway.proposals import JsonProposalStore
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
    ) -> None:
        self.repository = MarkdownVaultRepository(vault_path)
        self.store = JsonProposalStore(state_path)
        self.policies = dict(policies)

    def _policy(self, agent_id: str) -> AgentPolicy:
        try:
            return self.policies[agent_id]
        except KeyError as exc:
            self.store.audit(
                {"action": "permission_check", "agent": agent_id,
                 "decision": "denied", "reason": "unregistered_agent", "timestamp": _now()}
            )
            raise PermissionDenied("unregistered_agent") from exc

    @staticmethod
    def _matches(node: GatewayNode, query: str) -> bool:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return True
        haystack = " ".join((node.title, node.body, " ".join(node.domain))).casefold()
        return all(term in haystack for term in terms)

    def query_knowledge(self, query: str, *, agent_id: str) -> QueryResponse:
        policy = self._policy(agent_id)
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

    def get_context(self, task: str, *, agent_id: str) -> ContextResponse:
        nodes = self.query_knowledge(task, agent_id=agent_id).nodes
        return ContextResponse(
            knowledge=[node for node in nodes if node.type not in {"experience", "principle"}],
            experience=[node for node in nodes if node.type == "experience"],
            principles=[node for node in nodes if node.type == "principle"],
        )

    def request_update(
        self,
        *,
        agent_id: str,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
    ) -> Proposal:
        policy = self._policy(agent_id)
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
        if not old or not new or old == new:
            raise ProposalConflict("proposal must replace non-empty content")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if risk not in {"low", "medium", "high"}:
            raise ValueError("risk must be low, medium, or high")

        target = self.repository.resolve_node_path(node)
        content = target.read_text(encoding="utf-8")
        if content.count(old) != 1:
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
        self.store.audit(
            {"action": "request_update", "agent": agent_id, "proposal_id": proposal.proposal_id,
             "resource": target_id, "decision": "pending", "timestamp": proposal.created}
        )
        return proposal

    def approve_change(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        core_approval: bool = False,
    ) -> Proposal:
        if not reviewer.strip():
            raise ApprovalRequired("reviewer identity is required")
        proposal = self.store.load(proposal_id)
        if proposal.status != "pending":
            raise ProposalConflict("proposal is not pending")
        if proposal.requires_core_approval and not core_approval:
            raise ApprovalRequired("core approval is required")

        node = self.repository.find_by_id(proposal.target_id)
        if node is None or node.path != proposal.target_path:
            raise ProposalConflict("proposal target no longer exists")
        target = self.repository.resolve_node_path(node)
        content = target.read_text(encoding="utf-8")
        if _digest(content) != proposal.target_digest or content.count(proposal.old) != 1:
            raise ProposalConflict("proposal target changed after request")

        self.store.backup(proposal, content)
        updated_content = content.replace(proposal.old, proposal.new, 1)
        temporary = target.with_name(f".{target.name}.{proposal.proposal_id}.tmp")
        temporary.write_text(updated_content, encoding="utf-8")
        os.replace(temporary, target)

        approved = replace(proposal, status="approved", reviewer=reviewer, review_time=_now())
        self.store.save(approved)
        self.store.audit(
            {"action": "approve_change", "agent": proposal.agent, "approved_by": reviewer,
             "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
             "decision": "approved", "timestamp": approved.review_time}
        )
        return approved

    def reject_change(self, proposal_id: str, *, reviewer: str, reason: str) -> Proposal:
        if not reviewer.strip():
            raise ApprovalRequired("reviewer identity is required")
        if not reason.strip():
            raise ValueError("rejection reason is required")
        proposal = self.store.load(proposal_id)
        if proposal.status != "pending":
            raise ProposalConflict("proposal is not pending")
        rejected = replace(proposal, status="rejected", reviewer=reviewer, review_time=_now())
        self.store.save(rejected)
        self.store.audit(
            {"action": "reject_change", "agent": proposal.agent, "approved_by": reviewer,
             "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
             "decision": "rejected", "reason": reason, "timestamp": rejected.review_time}
        )
        return rejected

    def expire_change(self, proposal_id: str, *, reason: str) -> Proposal:
        if not reason.strip():
            raise ValueError("expiration reason is required")
        proposal = self.store.load(proposal_id)
        if proposal.status != "pending":
            raise ProposalConflict("proposal is not pending")
        expired = replace(proposal, status="expired", review_time=_now())
        self.store.save(expired)
        self.store.audit(
            {"action": "expire_change", "agent": proposal.agent,
             "proposal_id": proposal.proposal_id, "resource": proposal.target_id,
             "decision": "expired", "reason": reason, "timestamp": expired.review_time}
        )
        return expired
