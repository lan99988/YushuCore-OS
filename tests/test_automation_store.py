from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from yushuos.automation_store import AutomationStore


NOW = "2026-10-05T00:00:00Z"
REVISION_1 = "1" * 64
REVISION_2 = "2" * 64


def rule(rule_id="daily-review", revision=REVISION_1, **extra):
    return {
        "id": rule_id,
        "revision": revision,
        "enabled": True,
        "action": {"plugin_id": "calendar", "action_ref": "calendar.create"},
        "action_hash": "a" * 64,
        "pins": {"calendar": "1.2.3"},
        "trigger": {"kind": "cron", "expression": "0 9 * * *"},
        "project_ref": "project.demo",
        "next_due": NOW,
        **extra,
    }


def test_rule_store_is_separate_metadata_only_and_cursor_is_revision_cas(tmp_path):
    store = AutomationStore(tmp_path)
    private_marker = "PRIVATE_AUTOMATION_BODY_47"
    store.put_rule(rule(fields={"prompt": private_marker}, workflow={"steps": [private_marker]}))

    saved = store.get_rule("daily-review")
    assert saved["revision"] == REVISION_1
    assert saved["action"] == {"plugin_id": "calendar", "action_ref": "calendar.create"}
    assert "fields" not in saved and "workflow" not in saved
    assert store.path.name == "automation.sqlite"
    assert private_marker.encode() not in Path(store.path).read_bytes()
    assert store.set_enabled("daily-review", False) is True
    assert store.get_rule("daily-review")["enabled"] is False
    assert [item["id"] for item in store.list_rules()] == ["daily-review"]
    assert store.update_cursor("daily-review", REVISION_1, "2026-10-06T09:00:00Z") is True
    assert store.update_cursor("daily-review", REVISION_1, "2026-10-07T09:00:00Z") is True
    store.put_rule(rule(revision=REVISION_2))
    assert store.update_cursor("daily-review", REVISION_1, "2026-10-08T09:00:00Z") is False
    assert store.get_rule("daily-review")["next_due"] == "2026-10-05T00:00:00.000000Z"


def test_grant_requires_unexpired_and_not_revoked(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    grant = {"grant_id": "grant-1", "expires_at": "2026-10-05T00:00:01Z", "scopes": ["calendar.write"]}
    store.save_grant("daily-review", grant)
    assert store.active_grant("daily-review", NOW)["grant_id"] == grant["grant_id"]
    assert store.active_grant("daily-review", "2026-10-05T00:00:01Z") is None
    store.revoke("daily-review")
    assert store.active_grant("daily-review", NOW) is None


def test_event_envelope_is_idempotent_and_resource_refs_are_filtered(tmp_path):
    store = AutomationStore(tmp_path)
    event = {
        "id": "evt-1", "type": "calendar.created", "source_plugin": "calendar",
        "source_version": "1.2.3", "project_ref": "project.demo", "request_id": "req-1",
        "causation_id": "cause-1", "root_event_id": "root-1", "occurred_at": NOW,
        "depth": 1,
        "resource_refs": {
            "calendar_id": "cal-1", "event_id": "ev-1", "message": "secret", "data": "body",
            "ref": "https://user:password@example.test/events/1?token=secret#private",
        },
        "message": "must not be persisted",
    }
    store.publish_event(event)
    store.publish_event(event)
    pending = store.pending_events()
    assert len(pending) == 1
    assert pending[0]["resource_refs"] == {
        "calendar_id": "cal-1", "event_id": "ev-1", "ref": "https://example.test/events/1",
    }
    with pytest.raises(ValueError, match="冲突"):
        store.publish_event({**event, "type": "calendar.deleted"})
    store.mark_event_delivered("evt-1")
    assert store.pending_events() == []
    assert store.show_event("evt-1")["delivered"] is True
    assert store.list_events(delivered=True)[0]["id"] == "evt-1"


def test_purged_event_tombstone_preserves_provider_digest_identity(tmp_path):
    store = AutomationStore(tmp_path)
    event = {
        "id": "evt-digest-tombstone", "type": "calendar.created", "source_plugin": "calendar",
        "source_version": "1.2.3", "provider_digest": "a" * 64,
        "project_ref": "project.demo", "request_id": "req-1", "occurred_at": NOW,
        "depth": 0, "resource_refs": {},
    }
    store.publish_event(event)
    store.mark_event_delivered(event["id"])
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE automation_events SET created_at='2020-01-01T00:00:00.000000Z'")
    assert store.purge_history("2021-01-01T00:00:00Z")["events_purged"] == 1
    with pytest.raises(ValueError, match="冲突"):
        store.publish_event({**event, "provider_digest": "b" * 64})


def test_occurrences_are_revision_scoped_but_overlap_is_per_rule(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    first = store.enqueue_run(store.get_rule("daily-review"), "2026-10-05", NOW)
    assert first["status"] == "pending"
    duplicate = store.enqueue_run(store.get_rule("daily-review"), "2026-10-05", NOW)
    assert duplicate["run_id"] == first["run_id"]

    store.put_rule(rule(revision=REVISION_2))
    revised = store.enqueue_run(store.get_rule("daily-review"), "2026-10-05", NOW)
    assert revised["run_id"] != first["run_id"]
    assert revised["status"] == "overlap_skipped"
    assert revised["revision"] == REVISION_2
    assert len(store.list_runs(rule_id="daily-review")) == 2


def test_depth_limit_and_atomic_per_root_budget(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    too_deep = store.enqueue_run(store.get_rule("daily-review"), "deep", NOW,
                                root_event_id="root-deep", depth=9)
    assert too_deep["status"] == "blocked"
    assert too_deep["error_code"] == "depth_limit"

    def enqueue(i):
        return store.enqueue_run(store.get_rule("daily-review"), f"occ-{i}", NOW,
                                 root_event_id="root-budget", depth=1)

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(enqueue, range(257)))
    assert sum(row["status"] != "blocked" or row["error_code"] != "fanout_limit" for row in rows) == 256
    blocked = [row for row in rows if row["error_code"] == "fanout_limit"]
    assert len(blocked) == 1
    with sqlite3.connect(store.path) as db:
        count = db.execute("SELECT run_count FROM root_budgets WHERE root_event_id='root-budget'").fetchone()[0]
    assert count == 256


def test_expired_undispatched_run_can_be_reclaimed_but_old_generation_cannot_mutate(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "one", NOW)
    first = store.claim_run(run["run_id"], "worker-a", NOW, ttl=10)
    second_now = "2026-10-05T00:00:11Z"
    second = store.claim_run(run["run_id"], "worker-b", second_now, ttl=10)
    assert second["generation"] == first["generation"] + 1
    with pytest.raises(ValueError, match="租约"):
        store.update_run(run["run_id"], "worker-a", first["generation"], "succeeded", second_now)
    assert store.update_run(run["run_id"], "worker-b", second["generation"], "succeeded", second_now) is True


def test_expired_dispatched_run_becomes_unknown_and_is_never_reclaimed(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "dispatched", NOW)
    claimed = store.claim_run(run["run_id"], "worker-a", NOW, ttl=1)
    store.mark_dispatched(run["run_id"], "worker-a", claimed["generation"], "2026-10-05T00:00:00Z")
    expired = store.claim_run(run["run_id"], "worker-b", "2026-10-05T00:00:02Z", ttl=30)
    assert expired is None
    assert store.show_run(run["run_id"])["status"] == "unknown"


def test_host_pending_requires_explicit_release_and_unknown_is_not_released(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "host", NOW)
    claimed = store.claim_run(run["run_id"], "worker-a", NOW)
    store.update_run(run["run_id"], "worker-a", claimed["generation"], "host_pending", NOW)
    assert store.release_host_pending(run["run_id"]) is True
    claimed_again = store.claim_run(run["run_id"], "worker-a", NOW)
    store.update_run(run["run_id"], "worker-a", claimed_again["generation"], "unknown", NOW)
    assert store.release_host_pending(run["run_id"]) is False
    assert store.show_run(run["run_id"])["status"] == "unknown"


def test_history_purge_keeps_unknown_and_undelivered_events(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    complete = store.enqueue_run(store.get_rule("daily-review"), "complete", NOW)
    lease = store.claim_run(complete["run_id"], "worker-a", NOW)
    store.update_run(complete["run_id"], "worker-a", lease["generation"], "succeeded", NOW)
    uncertain = store.enqueue_run(store.get_rule("daily-review"), "uncertain", NOW)
    lease = store.claim_run(uncertain["run_id"], "worker-a", NOW)
    store.update_run(uncertain["run_id"], "worker-a", lease["generation"], "unknown", NOW)
    delivered = {
        "id": "old-event", "type": "calendar.created", "source_plugin": "calendar",
        "source_version": "1.2.3", "project_ref": "project.demo", "request_id": "req-1",
        "causation_id": "", "root_event_id": "old-event", "occurred_at": NOW,
        "depth": 0, "resource_refs": {},
    }
    pending = {**delivered, "id": "pending-event", "root_event_id": "pending-event"}
    store.publish_event(delivered)
    store.publish_event(pending)
    store.mark_event_delivered("old-event")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE automation_runs SET updated_at='2020-01-01T00:00:00.000000Z'")
        db.execute("UPDATE automation_events SET created_at='2020-01-01T00:00:00.000000Z'")
    purged = store.purge_history("2021-01-01T00:00:00Z")
    assert purged == {"runs_purged": 1, "events_purged": 1}
    assert store.show_run(uncertain["run_id"])["status"] == "unknown"
    assert [event["id"] for event in store.pending_events()] == ["pending-event"]


def test_resolved_run_stays_auditable_until_explicit_release(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "resolve-me", NOW)
    lease = store.claim_run(run["run_id"], "worker-a", NOW)
    store.mark_dispatched(run["run_id"], "worker-a", lease["generation"], NOW)
    store.claim_run(run["run_id"], "worker-b", "2026-10-05T00:00:31Z")
    assert store.show_run(run["run_id"])["status"] == "unknown"

    store.resolve_run(run["run_id"], "verified_failed", actor="user-1", reason_code="readback_failed",
                      evidence_ref="event-42")
    resolved = store.show_run(run["run_id"])
    assert resolved["status"] == "unknown"
    assert resolved["resolution"]["status"] == "verified_failed"
    assert store.release_resolved_run(run["run_id"]) is True
    released = store.show_run(run["run_id"])
    assert released["status"] == "pending"
    assert released["resolved_from"] == "unknown"
    assert released["dispatched"] is False
    assert released["resolution"]["status"] == "verified_failed"

    with pytest.raises(ValueError):
        store.resolve_run(run["run_id"], "verified_success", actor="user-1", reason_code="conflicting_readback")


def test_verified_success_can_release_unknown_workflow_for_explicit_continuation(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "verified-success", NOW)
    lease = store.claim_run(run["run_id"], "worker-a", NOW, ttl=1)
    store.mark_dispatched(run["run_id"], "worker-a", lease["generation"], NOW)
    store.claim_run(run["run_id"], "worker-b", "2026-10-05T00:00:02Z")
    store.resolve_run(run["run_id"], "verified_success", actor="user-1", reason_code="remote_readback")
    assert store.release_resolved_run(run["run_id"]) is True
    current = store.show_run(run["run_id"])
    assert current["status"] == "pending"
    assert current["resolved_from"] == "unknown"
    assert current["resolution"]["status"] == "verified_success"
    assert store.release_resolved_run(run["run_id"]) is False


def test_abandoned_run_resolution_never_releases_for_execution(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    run = store.enqueue_run(store.get_rule("daily-review"), "abandoned-run", NOW)
    lease = store.claim_run(run["run_id"], "worker-a", NOW)
    store.update_run(run["run_id"], "worker-a", lease["generation"], "abandoned", NOW)
    store.resolve_run(run["run_id"], "verified_failed", actor="user-1", reason_code="manual_abandon")
    assert store.release_resolved_run(run["run_id"]) is False
    assert store.show_run(run["run_id"])["status"] == "abandoned"


def test_history_purge_retains_run_occurrence_and_event_dedupe_identities(tmp_path):
    store = AutomationStore(tmp_path)
    store.put_rule(rule())
    value = store.get_rule("daily-review")
    run = store.enqueue_run(value, "old-occurrence", NOW, root_event_id="old-root")
    lease = store.claim_run(run["run_id"], "worker-a", NOW)
    store.update_run(run["run_id"], "worker-a", lease["generation"], "succeeded", NOW,
                     resource_refs={"event_id": "event-old"})
    event = {
        "id": "event-old", "type": "calendar.created", "source_plugin": "calendar",
        "source_version": "1.2.3", "project_ref": "project.demo", "request_id": "req-1",
        "causation_id": "", "root_event_id": "event-old", "occurred_at": NOW,
        "depth": 0, "resource_refs": {"event_id": "event-old"},
    }
    store.publish_event(event)
    store.mark_event_delivered("event-old")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE automation_runs SET updated_at='2020-01-01T00:00:00.000000Z'")
        db.execute("UPDATE automation_events SET created_at='2020-01-01T00:00:00.000000Z'")
    purged = store.purge_history("2021-01-01T00:00:00Z")
    assert purged["runs_purged"] == 1
    assert purged["events_purged"] == 1

    tombstone = store.show_run(run["run_id"])
    assert tombstone["purged"] is True
    assert tombstone["resource_refs"] == {}
    repeated = store.enqueue_run(value, "old-occurrence", NOW, root_event_id="old-root")
    assert repeated["run_id"] == run["run_id"]
    assert repeated["purged"] is True
    assert store.show_event("event-old")["purged"] is True
    assert store.publish_event(event)["id"] == "event-old"


def test_run_keeps_rule_and_grant_metadata_snapshots_across_rule_and_grant_updates(tmp_path):
    store = AutomationStore(tmp_path)
    first_rule = rule()
    saved = store.put_rule(first_rule)
    run = store.enqueue_run(saved, "frozen-metadata", NOW)
    grant = {
        "grant_id": "grant-old", "rule_id": "daily-review", "revision": REVISION_1,
        "action_hash": "a" * 64, "pins": {"calendar": "1.2.3"},
        "created_at": NOW, "expires_at": "2026-11-04T00:00:00Z",
        "canonicalization": "jcs-v1",
    }
    store.set_run_authorization(run["run_id"], grant)

    second_rule = rule(revision=REVISION_2, action_hash="b" * 64, trigger={"kind": "cron", "expression": "0 10 * * *"})
    store.put_rule(second_rule)
    store.save_grant("daily-review", {
        **grant, "grant_id": "grant-new", "revision": REVISION_2,
        "action_hash": "b" * 64,
    })
    history = store.show_run(run["run_id"])
    assert history["rule_snapshot"]["revision"] == REVISION_1
    assert history["rule_snapshot"]["action_hash"] == "a" * 64
    assert history["authorization"]["grant_id"] == "grant-old"
    assert history["authorization"]["pins"] == {"calendar": "1.2.3"}
    assert history["authorization_history"] == [history["authorization"]]


def test_run_authorization_renewal_is_append_only_and_cannot_change_rule_binding(tmp_path):
    store = AutomationStore(tmp_path)
    saved = store.put_rule(rule())
    run = store.enqueue_run(saved, "renew-authorization", NOW)
    grant = {
        "grant_id": "grant-old", "revision": REVISION_1, "action_hash": "a" * 64,
        "pins": {"calendar": "1.2.3"}, "expires_at": "2026-11-04T00:00:00Z",
    }
    store.set_run_authorization(run["run_id"], grant)
    renewed = {**grant, "grant_id": "grant-renewed", "expires_at": "2026-12-04T00:00:00Z"}
    store.set_run_authorization(run["run_id"], renewed)
    store.set_run_authorization(run["run_id"], renewed)
    history = store.show_run(run["run_id"])
    assert history["authorization"]["grant_id"] == "grant-old"
    assert [item["grant_id"] for item in history["authorization_history"]] == ["grant-old", "grant-renewed"]
    with pytest.raises(ValueError):
        store.set_run_authorization(run["run_id"], {**renewed, "pins": {"calendar": "9.9.9"}})


def test_request_id_lookup_uses_index_and_legacy_snapshot_fallback(tmp_path):
    from yushuos_sdk.canonical import request_id

    store = AutomationStore(tmp_path)
    pinned_rule = rule(pins={
        "steps": [{
            "step_id": "second", "plugin_id": "calendar", "version": "1.2.3",
            "provider_digest": "a" * 64, "capability": "calendar.create", "intent": "write",
            "effect": "external_write", "execution_mode": "plugin", "permissions": ["calendar.write"],
            "resource_hash": "b" * 64, "target_hash": "c" * 64,
        }],
        "providers": [{"plugin_id": "calendar", "version": "1.2.3", "provider_digest": "a" * 64}],
    })
    saved = store.put_rule(pinned_rule)
    run = store.enqueue_run(saved, "request-lookup", NOW)
    request = request_id(run["run_id"], "second")
    matches = store.find_runs_for_request(request, "project.demo")
    assert len(matches) == 1
    assert matches[0]["run"]["run_id"] == run["run_id"]
    assert matches[0]["step_id"] == "second"
    assert store.find_runs_for_request(request, "other.project") == []

    with sqlite3.connect(store.path) as db:
        db.execute("DELETE FROM automation_run_steps WHERE run_id=?", (run["run_id"],))
    assert store.find_runs_for_request(request, "project.demo")[0]["run"]["run_id"] == run["run_id"]
