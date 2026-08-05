from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from .models import CognitiveProposal, SelfModelLayer


class CognitiveProposalStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "audit.jsonl"

    def save(self, proposal: CognitiveProposal) -> None:
        path = self.root / f"{proposal.proposal_id}.json"
        payload = asdict(proposal)
        payload["target_layer"] = proposal.target_layer.value
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def load(self, proposal_id: str) -> CognitiveProposal:
        path = self.root / f"{proposal_id}.json"
        if not path.is_file():
            raise KeyError(proposal_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["target_layer"] = SelfModelLayer(payload["target_layer"])
        payload["evidence"] = tuple(payload.get("evidence", ()))
        return CognitiveProposal(**payload)

    def approve(self, proposal_id: str, *, reviewer: str) -> CognitiveProposal:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        proposal = self.load(proposal_id)
        if reviewer == proposal.agent_id:
            self._audit(proposal, "cognitive_proposal_approval_denied", reviewer, "separation_of_duties")
            raise PermissionError("reviewer must be different from agent")
        if proposal.status != "pending_human_review":
            raise ValueError("proposal is not pending human review")
        approved = replace(proposal, status="approved", approved=True)
        self.save(approved)
        self._audit(approved, "cognitive_proposal_approved", reviewer, "human_review")
        return approved

    def reject(self, proposal_id: str, *, reviewer: str, reason: str) -> CognitiveProposal:
        if not reviewer.strip() or not reason.strip():
            raise ValueError("reviewer and reason are required")
        proposal = self.load(proposal_id)
        if reviewer == proposal.agent_id:
            self._audit(proposal, "cognitive_proposal_rejection_denied", reviewer, "separation_of_duties")
            raise PermissionError("reviewer must be different from agent")
        if proposal.status != "pending_human_review":
            raise ValueError("proposal is not pending human review")
        rejected = replace(proposal, status="rejected", approved=False, reason=reason)
        self.save(rejected)
        self._audit(rejected, "cognitive_proposal_rejected", reviewer, "human_review")
        return rejected

    def audit_events(self) -> list[dict[str, object]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _audit(self, proposal: CognitiveProposal, action: str, reviewer: str, reason: str) -> None:
        event = {
            "action": action,
            "proposal_id": proposal.proposal_id,
            "agent_id": proposal.agent_id,
            "reviewer": reviewer,
            "reason": reason,
            "correlation_id": proposal.correlation_id,
            "timestamp": proposal.created_at,
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
