from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import re
from datetime import datetime

import yaml


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
        if source not in {"pdf", "web", "chat", "ai_chat", "wechat", "video", "image", "manual"}:
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


class Classifier:
    def classify(self, analyzed: AnalyzedCandidate) -> dict[str, object]:
        haystack = " ".join(
            (analyzed.capture.title, analyzed.capture.content, *analyzed.keywords)
        ).casefold()
        if any(token in haystack for token in ("sleep", "recovery", "training", "身体", "训练")):
            domain = "body"
        elif any(token in haystack for token in ("study", "learning", "exam", "学习", "考试")):
            domain = "study"
        elif any(token in haystack for token in ("project", "task", "项目", "任务")):
            domain = "project"
        else:
            domain = "knowledge"
        return {
            "suggested_domain": domain,
            "confidence": 0.7 if domain != "knowledge" else 0.5,
            "status": "candidate",
        }


class SchemaGenerator:
    def generate(self, analyzed: AnalyzedCandidate) -> SchemaCandidate:
        return KnowledgePipeline().generate_schema(analyzed)


class Importer:
    def to_markdown(self, captured: CaptureCandidate) -> str:
        metadata = {
            "id": f"CAP-{sha256(captured.content.encode('utf-8')).hexdigest()[:12]}",
            "type": "knowledge",
            "domain": "knowledge",
            "source": captured.source,
            "status": "candidate",
            "created": date.today().isoformat(),
            "updated": date.today().isoformat(),
            "agent_access": ["knowledge_agent"],
        }
        frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{frontmatter}\n---\n# {captured.title}\n\n{captured.content}\n"


class Reviewer:
    def review(self, node: SchemaCandidate) -> dict[str, object]:
        issues: list[str] = []
        if not node.analyzed.summary.strip():
            issues.append("missing_summary")
        if not node.metadata.get("source"):
            issues.append("missing_source")
        if not 0.0 <= float(node.metadata.get("confidence", 0.0)) <= 1.0:
            issues.append("invalid_confidence")
        return {
            "target_id": node.metadata["id"],
            "status": "review_required",
            "issues": issues,
            "confidence": node.metadata.get("confidence", 0.0),
        }


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


class KnowledgeAuditor:
    def audit(
        self,
        nodes: list[SchemaCandidate],
        *,
        today: date | None = None,
        stale_days: int = 365,
    ) -> list[dict[str, object]]:
        reference = today or date.today()
        known_ids = {str(node.metadata.get("id")) for node in nodes}
        findings: list[dict[str, object]] = []
        titles: dict[str, str] = {}
        for node in nodes:
            title = node.analyzed.capture.title
            digest = sha256(node.analyzed.capture.content.encode("utf-8")).hexdigest()
            if title in titles and titles[title] != digest:
                findings.append(
                    {
                        "kind": "conflict",
                        "target_id": node.metadata["id"],
                        "status": "draft",
                        "reason": "Knowledge nodes share a title but disagree on content.",
                    }
                )
            titles[title] = digest
            updated = node.metadata.get("updated")
            if updated:
                try:
                    updated_date = datetime.fromisoformat(str(updated)).date()
                except ValueError:
                    updated_date = None
                if updated_date and (reference - updated_date).days > stale_days:
                    findings.append(
                        {
                            "kind": "stale",
                            "target_id": node.metadata["id"],
                            "status": "draft",
                            "reason": "Knowledge has not been updated within the freshness window.",
                        }
                    )
            for relation in node.metadata.get("relations", []) or []:
                if str(relation) not in known_ids:
                    findings.append(
                        {
                            "kind": "broken_relation",
                            "target_id": node.metadata["id"],
                            "relation": relation,
                            "status": "draft",
                            "reason": "Knowledge relation points to a missing node.",
                        }
                    )
        return findings
