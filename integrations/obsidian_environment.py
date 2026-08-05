from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ObsidianEnvironment:
    """Read-only inspection of the installed Obsidian app and vault registry."""

    def __init__(self, *, installation_path: str | Path, config_path: str | Path | None = None) -> None:
        self.installation_path = Path(installation_path)
        self.config_path = Path(config_path) if config_path else self._default_config_path()

    @staticmethod
    def _default_config_path() -> Path:
        roaming = Path.home() / "AppData/Roaming/obsidian/obsidian.json"
        return roaming

    def inspect(self) -> dict[str, Any]:
        open_vault = None
        vault_count = 0
        if self.config_path.is_file():
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            vaults = payload.get("vaults", {})
            vault_count = len(vaults)
            for entry in vaults.values():
                if entry.get("open"):
                    open_vault = str(Path(entry["path"]).resolve())
                    break
        return {
            "installation": str(self.installation_path),
            "installed": self.installation_path.exists(),
            "config": str(self.config_path),
            "vault_count": vault_count,
            "open_vault": open_vault,
            "writable_by_adapter": False,
            "gateway_first": True,
        }
