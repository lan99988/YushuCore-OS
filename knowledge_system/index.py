from __future__ import annotations

import json
from pathlib import Path

from knowledge_system.parser.markdown import FrontMatterError, parse_markdown


class MarkdownIndex:
    def __init__(self, index_path: str | Path, *, root: str | Path | None = None) -> None:
        self.index_path = Path(index_path)
        self.root = Path(root) if root is not None else self.index_path.parent

    def build(self) -> int:
        entries: list[dict[str, object]] = []
        for path in sorted(self.root.rglob("*.md")):
            if path.resolve() == self.index_path.resolve():
                continue
            try:
                parsed = parse_markdown(path.read_text(encoding="utf-8"), path.relative_to(self.root).as_posix())
            except (OSError, FrontMatterError):
                continue
            metadata = parsed.metadata
            entries.append({
                "id": str(metadata.get("id", "")),
                "title": parsed.title or path.stem,
                "path": parsed.source_path,
                "domain": metadata.get("domain", []),
                "status": metadata.get("status", ""),
                "text": parsed.body[:1000],
            })
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.index_path)
        return len(entries)

    def entries(self) -> tuple[dict[str, object], ...]:
        if not self.index_path.exists():
            return ()
        return tuple(json.loads(self.index_path.read_text(encoding="utf-8")))

    def search(self, query: str) -> list[dict[str, object]]:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return list(self.entries())
        results = []
        for entry in self.entries():
            haystack = " ".join(str(entry.get(key, "")) for key in ("id", "title", "domain", "text")).casefold()
            if all(term in haystack for term in terms):
                results.append(entry)
        return results
