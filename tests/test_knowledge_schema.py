from datetime import date
import json
from pathlib import Path

import pytest

from knowledge_system.parser.markdown import FrontMatterError, parse_markdown
from knowledge_system.validator.metadata import validate_metadata


VALID_MARKDOWN = """---
id: KN-20260804-0001
type: model
title: 渐进式超负荷训练模型
domain: body
layer: 2
source:
  - personal_experience
author: owner
created: 2026-08-04
updated: 2026-08-04
status: validated
confidence: 0.85
importance: 0.8
tags:
  - training
relations: []
agent_access:
  - body_agent
attachments: []
version: "1.0"
---
# 渐进式超负荷训练模型

逐步增加训练刺激。
"""


def test_parse_markdown_returns_normalized_knowledge_metadata():
    document = parse_markdown(VALID_MARKDOWN, source_path="02_Knowledge/training.md")

    assert document.metadata["id"] == "KN-20260804-0001"
    assert document.metadata["domain"] == ["body"]
    assert document.metadata["source"] == ["personal_experience"]
    assert document.metadata["confidence"] == 0.85
    assert document.title == "渐进式超负荷训练模型"
    assert "逐步增加训练刺激" in document.body
    assert document.source_path.endswith("02_Knowledge/training.md")


def test_parse_markdown_rejects_missing_front_matter():
    with pytest.raises(FrontMatterError, match="front matter"):
        parse_markdown("# 没有元数据\n正文")


def test_validator_accepts_v3_knowledge_node():
    document = parse_markdown(VALID_MARKDOWN)

    result = validate_metadata(document.metadata)

    assert result.valid is True
    assert result.errors == []


def test_validator_reports_missing_required_fields_and_invalid_values():
    result = validate_metadata(
        {
            "id": "",
            "type": "unknown",
            "domain": [],
            "source": [],
            "status": "draft",
            "confidence": 1.2,
            "agent_access": "body_agent",
            "created": "not-a-date",
        }
    )

    assert result.valid is False
    assert {issue.field for issue in result.errors} >= {
        "id",
        "type",
        "domain",
        "status",
        "confidence",
        "agent_access",
        "created",
        "updated",
    }


def test_validator_warns_about_unknown_fields_without_rejecting_document():
    metadata = {
        "id": "KN-1",
        "type": "knowledge",
        "domain": ["common"],
        "source": ["manual"],
        "status": "candidate",
        "confidence": 0.5,
        "agent_access": [],
        "created": date(2026, 8, 4),
        "updated": date(2026, 8, 4),
        "future_field": "preserve-me",
    }

    result = validate_metadata(metadata)

    assert result.valid is True
    assert any(issue.field == "future_field" for issue in result.warnings)


def test_versioned_json_schema_declares_frozen_metadata_contract():
    schema_path = Path("knowledge_system/schema/knowledge_node.schema.json")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$schema"].startswith("https://json-schema.org/")
    assert set(schema["required"]) >= {
        "id",
        "type",
        "domain",
        "source",
        "confidence",
        "status",
        "agent_access",
        "created",
        "updated",
    }
    assert set(schema["properties"]["status"]["enum"]) == {
        "raw",
        "candidate",
        "reviewed",
        "validated",
        "permanent",
        "archived",
    }
