from __future__ import annotations


def build_task_proposal(title: str, *, evidence: list[str] | None = None) -> dict[str, object]:
    if not title.strip():
        raise ValueError("task title is required")
    return {
        "proposal_type": "task",
        "title": title.strip(),
        "evidence": list(evidence or []),
        "status": "pending_human_review",
        "execution_gateway": "feishu",
        "executed": False,
        "requires_human_review": True,
    }
