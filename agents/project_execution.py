from __future__ import annotations


def build_task_proposal(
    title: str,
    *,
    evidence: list[str] | None = None,
    project_id: str = "",
    assignee: str = "",
    due_at: str = "",
) -> dict[str, object]:
    if not title.strip():
        raise ValueError("task title is required")
    return {
        "proposal_type": "task",
        "title": title.strip(),
        "evidence": list(evidence or []),
        "project_id": project_id,
        "assignee": assignee,
        "due_at": due_at,
        "approval": {
            "status": "pending_human_review",
            "reviewer": None,
            "reviewed_at": None,
        },
        "status": "pending_human_review",
        "execution_gateway": "feishu",
        "executed": False,
        "requires_human_review": True,
    }


def build_project_plan(
    goal: str,
    *,
    task_status: dict[str, str] | None = None,
    progress: float = 0.0,
) -> dict[str, object]:
    if not goal.strip():
        raise ValueError("project goal is required")
    if not 0.0 <= progress <= 1.0:
        raise ValueError("progress must be between 0 and 1")
    statuses = dict(task_status or {})
    risks = [
        {"task": task, "risk": "blocked task requires review"}
        for task, status in statuses.items()
        if status.casefold() in {"blocked", "failed", "overdue"}
    ]
    return {
        "proposal_type": "project_plan",
        "goal": goal,
        "project_plan": {
            "progress": progress,
            "next_tasks": [task for task, status in statuses.items() if status.casefold() != "done"],
        },
        "risk_analysis": risks,
        "task_suggestions": [
            {"task": task, "status": status}
            for task, status in statuses.items()
            if status.casefold() != "done"
        ],
        "status": "draft",
        "requires_human_review": True,
    }
