from __future__ import annotations

from pathlib import Path

from knowledge_system.backup import VaultBackup


def create_backup(vault_root: str | Path, backup_root: str | Path) -> Path:
    return VaultBackup(backup_root).create(vault_root)
