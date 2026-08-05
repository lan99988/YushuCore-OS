from __future__ import annotations


def build_learning_plan(goal: str, topics: list[str]) -> dict[str, object]:
    ordered = list(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
    return {
        "proposal_type": "learning_plan",
        "goal": goal,
        "knowledge_map": ordered,
        "learning_path": ordered,
        "review_suggestions": [f"Review {topic} after practice" for topic in ordered],
        "task_suggestions": [f"Practice {topic}" for topic in ordered],
        "weak_points": ordered[:1],
        "knowledge_connections": [
            {"from": ordered[index], "to": ordered[index + 1]}
            for index in range(len(ordered) - 1)
        ],
        "status": "draft",
        "requires_human_review": True,
    }
