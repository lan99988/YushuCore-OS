from __future__ import annotations

from pathlib import Path

from knowledge_system.index import MarkdownIndex


def rebuild_index(vault_root: str | Path) -> int:
    root = Path(vault_root)
    return MarkdownIndex(root / ".system/index.json", root=root).build()
