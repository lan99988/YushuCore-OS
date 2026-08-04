from __future__ import annotations

import json
import os
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from knowledge_system.gateway.models import Proposal


class LockUnavailable(RuntimeError):
    pass


class JsonProposalStore:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path).resolve()
        self.proposals_path = self.root / "proposals"
        self.backups_path = self.root / "backups"
        self.transactions_path = self.root / "transactions"
        self.audit_path = self.root / "audit.jsonl"
        self.proposals_path.mkdir(parents=True, exist_ok=True)
        self.backups_path.mkdir(parents=True, exist_ok=True)
        self.transactions_path.mkdir(parents=True, exist_ok=True)

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

    def delete(self, proposal_id: str) -> None:
        (self.proposals_path / f"{proposal_id}.json").unlink(missing_ok=True)

    def backup(self, proposal: Proposal, content: str) -> Path:
        path = self.backups_path / f"{proposal.proposal_id}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def start_transaction(self, proposal: Proposal, original_content: str) -> None:
        updated_content = original_content.replace(proposal.old, proposal.new, 1)
        record = {
            "proposal_id": proposal.proposal_id,
            "target_path": proposal.target_path,
            "original_digest": hashlib.sha256(original_content.encode("utf-8")).hexdigest(),
            "updated_digest": hashlib.sha256(updated_content.encode("utf-8")).hexdigest(),
            "stage": "prepared",
        }
        target = self.transactions_path / f"{proposal.proposal_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)

    def transactions(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.transactions_path.glob("*.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
        return records

    def clear_transaction(self, proposal_id: str) -> None:
        (self.transactions_path / f"{proposal_id}.json").unlink(missing_ok=True)

    def audit(self, event: dict[str, Any]) -> None:
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    @contextmanager
    def approval_lock(self):
        path = self.root / "approval.lock"
        stream = path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise LockUnavailable("approval_in_progress") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
