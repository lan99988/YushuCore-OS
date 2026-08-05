from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeFinding:
    node_id: str
    title: str
    domain: str
    summary: str
    source_path: str


def proposal_body(node) -> str:
    lines = node.body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def analyze_context(context) -> list[KnowledgeFinding]:
    findings: list[KnowledgeFinding] = []
    for node in context.knowledge:
        summary = proposal_body(node)
        if not summary:
            continue
        domain = node.domain[0] if node.domain else ""
        findings.append(
            KnowledgeFinding(
                node_id=node.id,
                title=node.title,
                domain=domain,
                summary=summary,
                source_path=node.path,
            )
        )
    return findings
