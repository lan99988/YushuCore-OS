from __future__ import annotations

from pathlib import Path


class VaultLayout:
    DIRECTORIES = (
        "00_Inbox", "01_Capture", "02_Knowledge", "03_Principles", "04_Models",
        "05_Domains", "06_Projects", "07_Decisions", "08_Agent_Memory",
        "09_Templates", "10_Attachments", "11_Self_Model", "12_Decision_History",
        "90_Archive", "99_System",
    )

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def initialize(self, *, approved: bool) -> tuple[Path, ...]:
        if not approved:
            raise PermissionError("Human approval is required for Vault initialization")
        created = []
        for relative in self.DIRECTORIES:
            path = self.root / relative
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
        return tuple(created)
