from __future__ import annotations


class GoalExecutionPort:
    """Reserved Execution OS bridge; it creates proposals and never executes."""

    def task_proposal(self, *, goal_id: str, title: str, approved: bool) -> dict[str, object]:
        if not goal_id.strip() or not title.strip():
            raise ValueError("goal_id and title are required")
        return {
            "proposal_type": "goal_task",
            "goal_id": goal_id,
            "title": title,
            "status": "approved" if approved else "pending_human_review",
            "execution_gateway": "execution_os",
            "execution": False,
            "requires_human_review": not approved,
        }
