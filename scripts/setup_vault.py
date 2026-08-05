from __future__ import annotations

from pathlib import Path

from knowledge_system.vault import VaultLayout


def setup_vault(root: str | Path, *, approved: bool) -> tuple[Path, ...]:
    return VaultLayout(root).initialize(approved=approved)
