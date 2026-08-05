from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import re


@dataclass(frozen=True)
class CaptureCandidate:
    source: str
    title: str
    content: str
    destination: str = "00_Inbox"


@dataclass(frozen=True)
class AnalyzedCandidate:
    capture: CaptureCandidate
    summary: str
    keywords: tuple[str, ...]
    topics: tuple[str, ...]


@dataclass(frozen=True)
class SchemaCandidate:
    analyzed: AnalyzedCandidate
    metadata: dict[str, object]


class KnowledgePipeline:
    def capture(self, *, source: str, title: str, content: str) -> CaptureCandidate:
        if source not in {"pdf", "web", "chat", "ai_chat", "wechat", "video", "manual"}:
            raise ValueError("unsupported capture source")
        if not title.strip() or not content.strip():
            raise ValueError("title and content are required")
        return CaptureCandidate(source=source, title=title.strip(), content=content.strip())

    def analyze(self, captured: CaptureCandidate) -> AnalyzedCandidate:
        words = tuple(dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,}", captured.content)))
        return AnalyzedCandidate(captured, captured.content.splitlines()[0][:240], words[:8], ())

    def generate_schema(self, analyzed: AnalyzedCandidate) -> SchemaCandidate:
        digest = sha256(analyzed.capture.content.encode("utf-8")).hexdigest()[:12]
        metadata = {
            "id": f"KN-CAND-{digest}", "type": "knowledge", "domain": "knowledge",
            "source": analyzed.capture.source, "confidence": 0.6, "status": "candidate",
            "agent_access": ["knowledge_agent"], "created": date.today().isoformat(),
            "updated": date.today().isoformat(), "keywords": list(analyzed.keywords), "relations": [],
        }
        return SchemaCandidate(analyzed, metadata)


class Collector:
    def capture(self, *, source: str, title: str, content: str) -> CaptureCandidate:
        return KnowledgePipeline().capture(source=source, title=title, content=content)


class Analyzer:
    def analyze(self, captured: CaptureCandidate) -> AnalyzedCandidate:
        return KnowledgePipeline().analyze(captured)


class SchemaGenerator:
    def generate(self, analyzed: AnalyzedCandidate) -> SchemaCandidate:
        return KnowledgePipeline().generate_schema(analyzed)


class KnowledgeLibrarian:
    def inspect(self, nodes: list[SchemaCandidate]) -> list[dict[str, object]]:
        proposals: list[dict[str, object]] = []
        seen: dict[str, str] = {}
        titles: dict[str, str] = {}
        for node in nodes:
            digest = sha256(node.analyzed.capture.content.encode("utf-8")).hexdigest()
            duplicate = digest in seen
            if duplicate:
                proposals.append({"kind": "duplicate", "target_id": node.metadata["id"], "status": "draft", "reason": "Duplicate content detected."})
            else:
                seen[digest] = str(node.metadata["id"])
            title = node.analyzed.capture.title
            if title in titles and not duplicate:
                proposals.append({"kind": "conflict", "target_id": node.metadata["id"], "status": "draft", "reason": "Same title has conflicting content."})
            titles[title] = digest
            if not node.metadata.get("relations"):
                proposals.append({"kind": "orphan", "target_id": node.metadata["id"], "status": "draft", "reason": "No knowledge relations found."})
        return proposals


class Librarian(KnowledgeLibrarian):
    pass
