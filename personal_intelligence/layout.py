from __future__ import annotations

from pathlib import Path


class SelfModelLayout:
    """Creates only the documented empty layout after explicit Human approval."""

    DIRECTORIES = (
        "11_Self_Model/identity",
        "11_Self_Model/values",
        "11_Self_Model/goals",
        "11_Self_Model/preferences",
        "11_Self_Model/thinking_patterns",
        "11_Self_Model/decision_models",
        "11_Self_Model/behavior_patterns",
        "11_Self_Model/strengths",
        "11_Self_Model/weaknesses",
        "11_Self_Model/beliefs",
        "12_Decision_History/decisions",
        "12_Decision_History/outcomes",
        "12_Decision_History/lessons",
        "12_Decision_History/adjustments",
    )

    def __init__(self, vault_root: str | Path) -> None:
        self.root = Path(vault_root)

    def initialize(self, *, human_approved: bool) -> tuple[Path, ...]:
        if not human_approved:
            raise PermissionError("Human approval is required to initialize Self Model layout")
        created: list[Path] = []
        for relative in self.DIRECTORIES:
            path = self.root / relative
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
        return tuple(created)
