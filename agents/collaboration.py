from __future__ import annotations

from typing import Any


def build_body_low_energy_proposals(event: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if event.get("event") != "body_low_energy":
        raise ValueError("event must be body_low_energy")
    payload = dict(event.get("payload", {}) or {})
    return {
        "study": {
            "proposal_type": "learning_adjustment",
            "reason": "Body Agent reported low energy; reduce cognitive load.",
            "evidence": payload,
            "suggestion": "Prioritize review over new material.",
            "status": "draft",
            "requires_human_review": True,
        },
        "project": {
            "proposal_type": "task_adjustment",
            "reason": "Body Agent reported low energy; rebalance project execution.",
            "evidence": payload,
            "suggestion": "Defer non-critical tasks and keep approved commitments visible.",
            "status": "pending_human_review",
            "requires_human_review": True,
        },
    }
