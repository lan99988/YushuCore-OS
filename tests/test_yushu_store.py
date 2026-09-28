from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from yushu_app.profile import Profile
from yushu_app.store import LocalStore, RecordConflict


def test_local_record_survives_reopen_and_idempotent_replay(tmp_path: Path):
    profile = Profile.initialize("default", home=tmp_path)
    store = LocalStore(profile)

    first = store.create(
        "task",
        {"title": "写周报", "status": "open"},
        actor="agent:a",
        correlation_id="corr-1",
        idempotency_key="capture-1",
    )
    repeated = LocalStore(Profile.open("default", home=tmp_path)).create(
        "task",
        {"title": "写周报", "status": "open"},
        actor="agent:a",
        correlation_id="corr-1",
        idempotency_key="capture-1",
    )

    assert repeated == first
    assert LocalStore(profile).list("task") == [first]
    assert first["version"] == 1


def test_idempotency_key_cannot_be_reused_with_new_payload(tmp_path: Path):
    store = LocalStore(Profile.initialize("default", home=tmp_path))
    store.create("task", {"title": "A"}, actor="agent:a", correlation_id="c", idempotency_key="same")

    with pytest.raises(RecordConflict, match="idempotency"):
        store.create("task", {"title": "B"}, actor="agent:a", correlation_id="c", idempotency_key="same")


def test_versioned_update_rejects_stale_writer(tmp_path: Path):
    store = LocalStore(Profile.initialize("default", home=tmp_path))
    original = store.create("goal", {"title": "学习", "status": "active"}, actor="owner", correlation_id="c")

    updated = store.update(
        "goal", original["id"], {"title": "学习", "status": "done"},
        expected_version=1, actor="owner", correlation_id="c2",
    )

    assert updated["version"] == 2
    with pytest.raises(RecordConflict, match="version"):
        store.update(
            "goal", original["id"], {"title": "old"},
            expected_version=1, actor="agent:a", correlation_id="c3",
        )


def test_audit_records_digests_not_private_payload(tmp_path: Path):
    profile = Profile.initialize("default", home=tmp_path)
    store = LocalStore(profile)
    store.create("information", {"content": "PRIVATE-SECRET"}, actor="agent:a", correlation_id="c")

    with sqlite3.connect(profile.database_path) as connection:
        audit = connection.execute("SELECT actor, correlation_id, payload_digest FROM audit_events").fetchone()

    assert audit[0:2] == ("agent:a", "c")
    assert len(audit[2]) == 64
    assert "PRIVATE-SECRET" not in str(audit)


def test_backup_is_consistent_and_readable(tmp_path: Path):
    store = LocalStore(Profile.initialize("default", home=tmp_path))
    store.create("task", {"title": "备份事项"}, actor="owner", correlation_id="c")

    destination = tmp_path / "backup.sqlite3"
    checksum = store.backup(destination)

    assert len(checksum) == 64
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 1


def test_restore_recovers_backup_and_preserves_pre_restore_copy(tmp_path: Path):
    profile = Profile.initialize("default", home=tmp_path)
    store = LocalStore(profile)
    store.create("task", {"title": "A"}, actor="owner", correlation_id="c1")
    backup = tmp_path / "backup.sqlite3"
    store.backup(backup)
    store.create("task", {"title": "B"}, actor="owner", correlation_id="c2")

    rescue = store.restore(backup)

    assert len(store.list("task")) == 1
    assert rescue.is_file()
    with sqlite3.connect(rescue) as connection:
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 2
