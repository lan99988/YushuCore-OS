from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from knowledge_system.gateway.models import Proposal


class JsonProposalStore:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path).resolve()
        self.proposals_path = self.root / "proposals"
        self.backups_path = self.root / "backups"
        self.audit_path = self.root / "audit.jsonl"
        self.proposals_path.mkdir(parents=True, exist_ok=True)
        self.backups_path.mkdir(parents=True, exist_ok=True)

    def save(self, proposal: Proposal) -> None:
        target = self.proposals_path / f"{proposal.proposal_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)

    def load(self, proposal_id: str) -> Proposal:
        if not proposal_id or any(character not in "0123456789abcdef-" for character in proposal_id):
            raise KeyError(proposal_id)
        path = self.proposals_path / f"{proposal_id}.json"
        if not path.is_file():
            raise KeyError(proposal_id)
        return Proposal.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def backup(self, proposal: Proposal, content: str) -> Path:
        path = self.backups_path / f"{proposal.proposal_id}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def audit(self, event: dict[str, Any]) -> None:
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
