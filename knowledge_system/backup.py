from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path


class VaultBackup:
    def __init__(self, backup_root: str | Path) -> None:
        self.root = Path(backup_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, vault_root: str | Path) -> Path:
        source = Path(vault_root).resolve()
        if not source.is_dir():
            raise FileNotFoundError(source)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.root / f"vault-{stamp}"
        return Path(shutil.make_archive(str(target), "zip", root_dir=source))

    def restore(self, archive: str | Path, vault_root: str | Path, *, approved: bool) -> None:
        if not approved:
            raise PermissionError("Human approval is required for Vault restore")
        archive_path = Path(archive).resolve()
        target = Path(vault_root).resolve()
        if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
            raise ValueError("restore archive must be a ZIP file")
        temporary = target.with_name(f".{target.name}.restore")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.unpack_archive(str(archive_path), str(temporary), format="zip")
        if target.exists():
            shutil.rmtree(target)
        temporary.replace(target)
