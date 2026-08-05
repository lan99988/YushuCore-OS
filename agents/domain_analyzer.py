from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainFinding:
    node_id: str
    title: str
    domain: str
    summary: str
    source_path: str


def _body_text(node) -> str:
    lines = node.body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def analyze_context(context, *, domain_name: str) -> list[DomainFinding]:
    findings: list[DomainFinding] = []
    for node in context.knowledge:
        if domain_name not in set(node.domain):
            continue
        summary = _body_text(node)
        if not summary:
            continue
        findings.append(
            DomainFinding(
                node_id=node.id,
                title=node.title,
                domain=domain_name,
                summary=summary,
                source_path=node.path,
            )
        )
    return findings
