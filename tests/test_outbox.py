import json
import sqlite3

import pytest

from yushuos_sdk.contracts import Request, Result
from yushuos_sdk.state import StateStore


def context(request_id="request-1", *, causation_id="cause-1", root_event_id="root-1", depth=1, run_id="run-1"):
    return {
        "plugin_id": "calendar", "plugin_version": "1.2.3", "provider_digest": "f" * 64,
        "project_ref": "project.demo",
        "request_id": request_id, "causation_id": causation_id, "root_event_id": root_event_id,
        "run_id": run_id, "depth": depth, "emitted_events": ["calendar.created"],
    }


def test_receipt_and_outbox_commit_together_with_deterministic_ids_and_privacy(tmp_path):
    ledger = tmp_path / "operations.sqlite3"
    store = StateStore(ledger)
    request = Request("request-1", "calendar.create", "write", {"title": "PRIVATE_REQUEST_BODY"},
                      project_ref="project.demo")
    assert store.claim(request)
    store._bind_context(request, context())
    result = Result("succeeded", request.request_id, "PRIVATE_MESSAGE",
                    resource={"event_id": "event-1", "message": "PRIVATE_RESOURCE"},
                    data={"private": "PRIVATE_RESULT_DATA"})
    emissions = [{"type": "calendar.created", "resource_refs": {"event_id": "event-1", "data": "PRIVATE_EVENT_BODY"}}]

    store.record_with_events(result, context(), emissions)
    first = store.pending_outbox()
    assert len(first) == 1
    first_event = first[0]["envelope"]
    assert first_event["id"]
    assert first_event["type"] == "calendar.created"
    assert first_event["provider_digest"] == "f" * 64
    assert first_event["resource_refs"] == {"event_id": "event-1"}
    assert first_event["depth"] == 2
    assert first_event["root_event_id"] == "root-1"
    store.record_with_events(result, context(), emissions)
    assert store.pending_outbox() == first
    assert store.mark_outbox_imported(first_event["id"]) is True
    assert store.mark_outbox_imported(first_event["id"]) is False
    assert store.pending_outbox() == []

    raw = ledger.read_bytes()
    for marker in ("PRIVATE_REQUEST_BODY", "PRIVATE_MESSAGE", "PRIVATE_RESOURCE", "PRIVATE_RESULT_DATA", "PRIVATE_EVENT_BODY"):
        assert marker.encode() not in raw
    receipt = store.receipt("request-1")
    assert receipt["receipt"] == {"status": "succeeded", "request_id": "request-1"}


def test_outbox_rejects_unclaimed_mismatched_and_unapproved_emissions(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    result = Result("succeeded", "request-1")
    with pytest.raises(ValueError, match="台账"):
        store.record_with_events(result, context(), [])

    request = Request("request-1", "calendar.create", "write", project_ref="project.demo")
    store.claim(request)
    store._bind_context(request, context())
    with pytest.raises(ValueError, match="request_id"):
        store.record_with_events(result, context("another-request"), [])
    with pytest.raises(ValueError, match="未授权"):
        store.record_with_events(result, context(), [{"type": "calendar.deleted", "resource_refs": {}}])
    with pytest.raises(ValueError):
        store.record_with_events(result, context(), [{"type": "calendar.created", "source_plugin": "spoofed"}])
    assert store.receipt("request-1")["receipt"] is None
    assert store.pending_outbox() == []


def test_outbox_requires_core_bound_identity_and_does_not_store_context_paths(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("request-1", "calendar.create", "write", project_ref="project.demo")
    assert store.claim(request)
    result = Result("succeeded", request.request_id)
    emissions = [{"type": "calendar.created", "resource_refs": {"event_id": "event-1"}}]

    with pytest.raises(ValueError, match="绑定"):
        store.record_with_events(result, context(), emissions)

    trusted = {**context(), "data_path": "PRIVATE_DATA_PATH", "resources": {"token": "PRIVATE_TOKEN"}}
    assert store._bind_context(request, trusted) is True
    with sqlite3.connect(store.path) as db:
        encoded = db.execute("SELECT context_json FROM operation_contexts WHERE request_id=?",
                             (request.request_id,)).fetchone()[0]
    assert "PRIVATE_DATA_PATH" not in encoded
    assert "PRIVATE_TOKEN" not in encoded

    attacker = {**context(), "plugin_id": "other-plugin", "provider_digest": "e" * 64}
    with pytest.raises(ValueError, match="身份"):
        store.record_with_events(result, attacker, emissions)
    assert store.pending_outbox() == []


def test_automation_event_keeps_valid_provider_digest_and_rejects_invalid_digest(tmp_path):
    from yushuos.automation_store import AutomationStore

    store = AutomationStore(tmp_path)
    event = {
        "id": "evt-digest", "type": "calendar.created", "source_plugin": "calendar",
        "source_version": "1.2.3", "provider_digest": "a" * 64, "project_ref": "project.demo",
        "request_id": "req-1", "occurred_at": "2026-10-05T00:00:00Z", "depth": 0,
        "resource_refs": {},
    }
    assert store.publish_event(event)["provider_digest"] == "a" * 64
    with pytest.raises(ValueError, match="provider_digest"):
        store.publish_event({**event, "id": "evt-bad-digest", "provider_digest": "not-a-digest"})


def test_unknown_result_does_not_publish_success_events(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("request-1", "calendar.create", "write", project_ref="project.demo")
    store.claim(request)
    store._bind_context(request, context())
    store.record_with_events(Result("unknown", request.request_id, "PRIVATE_UNKNOWN_MESSAGE"), context(), [
        {"type": "calendar.created", "resource_refs": {"event_id": "event-1"}},
    ])
    assert store.pending_outbox() == []
    assert store.receipt("request-1")["receipt"]["status"] == "unknown"
    assert b"PRIVATE_UNKNOWN_MESSAGE" not in (tmp_path / "operations.sqlite3").read_bytes()


def test_manual_emission_starts_a_root_and_strips_reference_url_credentials(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("request-1", "calendar.create", "write", project_ref="project.demo")
    store.claim(request)
    store._bind_context(request, context(causation_id="", root_event_id="", depth=7))
    store.record_with_events(Result("succeeded", request.request_id),
                             context(causation_id="", root_event_id="", depth=7), [
        {"type": "calendar.created", "resource_refs": {
            "ref": "https://user:password@example.test/events/1?token=secret#private",
        }},
    ])
    event = store.pending_outbox()[0]["envelope"]
    assert event["depth"] == 0
    assert event["root_event_id"] == event["id"]
    assert event["resource_refs"]["ref"] == "https://example.test/events/1"


def test_sqlite_outbox_failpoint_rolls_back_receipt_in_same_transaction(tmp_path):
    ledger = tmp_path / "operations.sqlite3"
    store = StateStore(ledger)
    request = Request("request-1", "calendar.create", "write", project_ref="project.demo")
    store.claim(request)
    store._bind_context(request, context())
    before = store.receipt("request-1")["receipt"]
    with sqlite3.connect(ledger) as db:
        db.execute("""
            CREATE TRIGGER fail_outbox_insert BEFORE INSERT ON event_outbox
            BEGIN SELECT RAISE(ABORT, 'failpoint'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="failpoint"):
        store.record_with_events(Result("succeeded", request.request_id), context(), [
            {"type": "calendar.created", "resource_refs": {"event_id": "event-1"}},
        ])
    assert store.receipt("request-1")["receipt"] == before
    assert store.pending_outbox() == []


def test_resolution_appends_without_rewriting_receipt_and_abandoned_keeps_lock(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("request-1", "calendar.create", "write", target={"calendar_id": "calendar-1"})
    store.claim(request)
    store.record(Result("unknown", request.request_id, "PRIVATE_MESSAGE"))
    original = store.receipt(request.request_id)["receipt"]
    store.resolve(request.request_id, "abandoned", actor="user-1", reason_code="cannot_verify")
    assert store.receipt(request.request_id)["receipt"] == original
    assert store.effective_receipt(request.request_id)["status"] == "abandoned"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT request_id FROM locks WHERE request_id=?", (request.request_id,)).fetchone()

    store.resolve(request.request_id, "abandoned", actor="user-1", reason_code="cannot_verify")
    with pytest.raises(ValueError):
        store.resolve(request.request_id, "verified_success", actor="user-1", reason_code="remote_readback",
                      evidence_ref="event-1")

    verified_request = Request("request-2", "calendar.create", "write")
    store.claim(verified_request)
    store.record(Result("unknown", verified_request.request_id, "PRIVATE_MESSAGE"))
    store.resolve(verified_request.request_id, "verified_success", actor="user-1", reason_code="remote_readback",
                  evidence_ref="event-1")
    effective = store.effective_receipt(verified_request.request_id)
    assert effective["status"] == "succeeded"
    assert effective["original_status"] == "unknown"
    assert effective["receipt"]["status"] == "succeeded"
    assert effective["original_receipt"] == {"status": "unknown", "request_id": "request-2"}
    store.resolve(verified_request.request_id, "verified_success", actor="user-1", reason_code="remote_readback",
                  evidence_ref="event-1")
    with pytest.raises(ValueError):
        store.resolve(verified_request.request_id, "verified_failed", actor="user-1", reason_code="remote_readback")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT 1 FROM locks WHERE request_id=?", (request.request_id,)).fetchone()
        assert db.execute("SELECT 1 FROM locks WHERE request_id=?", (verified_request.request_id,)).fetchone() is None
        rows = db.execute("SELECT outcome FROM receipt_resolutions WHERE request_id=? ORDER BY id", (verified_request.request_id,)).fetchall()
    assert [row[0] for row in rows] == ["verified_success"]


def test_explicit_success_or_failure_receipt_cannot_be_resolved(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("request-1", "calendar.create", "write")
    store.claim(request)
    store.record(Result("succeeded", request.request_id))
    with pytest.raises(ValueError):
        store.resolve(request.request_id, "verified_failed", actor="user-1", reason_code="conflict")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipt_resolutions").fetchone()[0] == 0


def test_effective_receipt_reads_legacy_v1_ledger_without_migrating_it(tmp_path):
    from pathlib import Path

    ledger = tmp_path / "legacy.sqlite3"
    script = Path(__file__).parent / "fixtures" / "v2" / "legacy-ledger.sql"
    with sqlite3.connect(ledger) as db:
        db.executescript(script.read_text(encoding="utf-8"))
    store = StateStore(ledger)
    value = store.effective_receipt("legacy-request-1")
    assert value["status"] == "succeeded"
    assert value["receipt"]["message"] == "legacy receipt retained"
    assert value["resolution"] is None
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipt_resolutions'").fetchone() is None
