import hashlib
import importlib
import importlib.util
import json
from dataclasses import dataclass

import pytest

from runtime_core.events import EventBus
from runtime_core.logger import RuntimeLogger


def _audit_api():
    spec = importlib.util.find_spec("runtime_core.audit")
    assert spec is not None, "runtime_core.audit is required for metadata-only audit"
    return importlib.import_module("runtime_core.audit")


def _record(**overrides):
    AuditRecord = _audit_api().AuditRecord
    values = {
        "actor": "agent:planner",
        "operation": "calendar.create_event",
        "resource": "plugin:calendar",
        "decision": "approval_required",
        "reason_code": "external_commitment",
        "correlation_id": "corr-17",
        "timestamp": "2026-09-26T12:00:00+00:00",
        "result": "pending_approval",
        "plugin_id": "calendar",
        "capability": "calendar.create_event",
        "payload_digest": hashlib.sha256(b"safe payload").hexdigest(),
    }
    values.update(overrides)
    return AuditRecord(**values)


def test_canonical_payload_digest_is_stable_across_mapping_order():
    canonical_payload_digest = _audit_api().canonical_payload_digest
    first = {"name": "日历", "nested": {"b": 2, "a": 1}}
    second = {"nested": {"a": 1, "b": 2}, "name": "日历"}

    digest = canonical_payload_digest(first)

    assert digest == canonical_payload_digest(second)
    assert len(digest) == 64
    assert digest == hashlib.sha256(
        json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_canonical_payload_digest_rejects_non_json_values():
    canonical_payload_digest = _audit_api().canonical_payload_digest
    with pytest.raises((TypeError, ValueError)):
        canonical_payload_digest({"not_json": object()})


def test_audit_record_contains_digest_but_no_raw_payload_field():
    AuditRecord = _audit_api().AuditRecord
    record = _record()

    assert record.payload_digest == hashlib.sha256(b"safe payload").hexdigest()
    assert "payload" not in record.__dataclass_fields__


def test_audit_logger_appends_metadata_only_jsonl(tmp_path):
    audit_api = _audit_api()
    AuditLogger = audit_api.AuditLogger
    logger = AuditLogger(tmp_path)
    record = _record()

    logger.write(record)

    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved == {
        "actor": "agent:planner",
        "operation": "calendar.create_event",
        "resource": "plugin:calendar",
        "decision": "approval_required",
        "reason_code": "external_commitment",
        "correlation_id": "corr-17",
        "timestamp": "2026-09-26T12:00:00+00:00",
        "result": "pending_approval",
        "plugin_id": "calendar",
        "capability": "calendar.create_event",
        "payload_digest": hashlib.sha256(b"safe payload").hexdigest(),
    }
    assert "payload" not in saved
    assert "safe payload" not in lines[0]


def test_audit_logger_rejects_record_subclass_with_extra_payload(tmp_path):
    audit_api = _audit_api()

    @dataclass(frozen=True)
    class InjectedAuditRecord(audit_api.AuditRecord):
        payload: str = "SENSITIVE-AUDIT-INJECTION"

    logger = audit_api.AuditLogger(tmp_path)

    with pytest.raises(TypeError, match="exact AuditRecord"):
        logger.write(InjectedAuditRecord(**_record().__dict__))

    assert not (tmp_path / "audit.jsonl").exists()


def test_audit_redacts_sensitive_payload(tmp_path):
    sentinel = "SENSITIVE-SENTINEL-7e9c"
    event = {
        "event": "agent_started",
        "agent_id": "agent:planner",
        "payload_digest": hashlib.sha256(b"already summarized").hexdigest(),
        "content_digest": hashlib.sha256(b"already summarized").hexdigest(),
        "task": sentinel,
        "payload": {"content": sentinel, "nested": {"credential": sentinel}},
        "message": sentinel,
        "body": sentinel,
        "text": sentinel,
        "old": sentinel,
        "new": sentinel,
        "secret": sentinel,
        "financial_screenshot": sentinel,
        "health_raw_data": sentinel,
    }
    bus = EventBus()
    runtime_logger = RuntimeLogger(tmp_path)
    received = []
    bus.subscribe(runtime_logger.write)
    bus.subscribe(received.append)

    bus.publish(event)

    history_event = bus.history[0]
    persisted_event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert received == [history_event]
    assert history_event["event"] == "agent_started"
    assert history_event["agent_id"] == "agent:planner"
    assert history_event["payload_digest"] == hashlib.sha256(b"already summarized").hexdigest()
    assert history_event["content_digest"] == hashlib.sha256(b"already summarized").hexdigest()
    assert sentinel not in json.dumps(history_event, ensure_ascii=False)
    assert sentinel not in json.dumps(persisted_event, ensure_ascii=False)
    assert persisted_event == history_event
    assert event["task"] == sentinel


def test_event_history_redaction_does_not_mutate_nested_original_or_handler_event():
    sentinel = "BODY-SENTINEL-14aa"
    event = {"event": "collaboration", "payload": {"content": sentinel, "safe": "kept"}}
    bus = EventBus()
    received = []
    bus.subscribe(received.append)

    bus.publish(event)

    assert received[0] == bus.history[0]
    assert received[0]["payload"]["redacted"] is True
    assert event["payload"]["content"] == sentinel
    assert sentinel not in json.dumps(bus.history[0], ensure_ascii=False)


@pytest.mark.parametrize(
    "sensitive_key",
    ["body_text", "message_text", "prompt", "user_prompt", "prompt_text"],
)
def test_event_history_redacts_composite_body_and_prompt_keys(sensitive_key):
    sentinel = f"COMPOSITE-SENTINEL-{sensitive_key}"
    event = {"event": "agent_input", sensitive_key: sentinel}
    bus = EventBus()

    bus.publish(event)

    assert sentinel not in json.dumps(bus.history[0], ensure_ascii=False)
