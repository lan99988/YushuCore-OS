"""Read-only Markdown and YAML front matter parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml


class FrontMatterError(ValueError):
    """Raised when a Markdown document has invalid or missing front matter."""


@dataclass(frozen=True)
class ParsedDocument:
    metadata: dict[str, Any]
    body: str
    title: str | None
    source_path: str


def _as_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return value


def _heading_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title or None
    return None


def parse_markdown(text: str, source_path: str = "") -> ParsedDocument:
    """Parse a Markdown string without reading or modifying the filesystem."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise FrontMatterError("Markdown front matter must start on the first line")

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise FrontMatterError("Markdown front matter is missing its closing delimiter")

    yaml_text = "".join(lines[1:closing_index])
    try:
        metadata = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"Invalid YAML front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise FrontMatterError("Markdown front matter must be a YAML mapping")

    normalized = dict(metadata)
    normalized["domain"] = _as_list(normalized.get("domain"))
    normalized["source"] = _as_list(normalized.get("source"))
    body = "".join(lines[closing_index + 1 :]).lstrip("\r\n")
    title = normalized.get("title") or _heading_title(body)
    normalized_path = str(PurePosixPath(source_path.replace("\\", "/"))) if source_path else ""
    return ParsedDocument(normalized, body, title, normalized_path)
