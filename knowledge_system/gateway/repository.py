from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from pathlib import Path

from knowledge_system.gateway.models import GatewayNode
from knowledge_system.parser.markdown import FrontMatterError, parse_markdown
from knowledge_system.validator.metadata import validate_metadata


@dataclass(frozen=True)
class RepositoryScan:
    nodes: list[GatewayNode]
    invalid_count: int


class MarkdownVaultRepository:
    def __init__(self, vault_path: str | Path) -> None:
        self.root = Path(vault_path).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Vault path does not exist: {self.root}")

    def scan(self) -> RepositoryScan:
        nodes: list[GatewayNode] = []
        invalid_count = 0
        for path in sorted(self.root.rglob("*.md")):
            try:
                relative = path.resolve().relative_to(self.root).as_posix()
                document = parse_markdown(path.read_text(encoding="utf-8"), relative)
                validation = validate_metadata(document.metadata)
            except (FrontMatterError, OSError, UnicodeError, ValueError):
                invalid_count += 1
                continue
            if not validation.valid:
                invalid_count += 1
                continue
            metadata = document.metadata
            nodes.append(
                GatewayNode(
                    id=metadata["id"],
                    type=metadata["type"],
                    title=str(metadata.get("title") or document.title or metadata["id"]),
                    domain=tuple(metadata["domain"]),
                    status=metadata["status"],
                    confidence=float(metadata["confidence"]),
                    sensitivity=str(
                        metadata.get("sensitivity")
                        or (metadata.get("agent_access") if isinstance(metadata.get("agent_access"), str) else "level_0")
                    ),
                    path=relative,
                    body=document.body,
                    metadata=metadata,
                )
            )
        counts = Counter(node.id for node in nodes)
        duplicate_ids = {node_id for node_id, count in counts.items() if count > 1}
        if duplicate_ids:
            duplicate_count = sum(1 for node in nodes if node.id in duplicate_ids)
            nodes = [node for node in nodes if node.id not in duplicate_ids]
            invalid_count += duplicate_count
        return RepositoryScan(nodes=nodes, invalid_count=invalid_count)

    def find_by_id(self, node_id: str) -> GatewayNode | None:
        matches = [node for node in self.scan().nodes if node.id == node_id]
        if len(matches) > 1:
            raise ValueError(f"Duplicate Knowledge Node id: {node_id}")
        return matches[0] if matches else None

    def resolve_node_path(self, node: GatewayNode) -> Path:
        path = (self.root / Path(node.path)).resolve()
        path.relative_to(self.root)
        return path

    def validate_replacement(self, node: GatewayNode, content: str) -> None:
        document = parse_markdown(content, node.path)
        validation = validate_metadata(document.metadata)
        if not validation.valid:
            details = ", ".join(f"{issue.field}:{issue.code}" for issue in validation.errors)
            raise ValueError(f"replacement metadata validation failed: {details}")
        if document.metadata["id"] != node.id:
            raise ValueError("replacement cannot change Knowledge Node id")
        for other in self.scan().nodes:
            if other.path != node.path and other.id == document.metadata["id"]:
                raise ValueError("replacement would create a duplicate Knowledge Node id")
