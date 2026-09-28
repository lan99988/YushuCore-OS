from __future__ import annotations

from pathlib import Path

import pytest

from capability_plugins.local_record.plugin import LocalRecordPlugin, LocalRecordPluginError
from yushu_app.profile import Profile
from yushu_app.store import LocalStore


def test_local_record_plugin_creates_and_lists_through_profile_store(tmp_path: Path):
    profile = Profile.initialize("default", home=tmp_path)
    plugin = LocalRecordPlugin(LocalStore(profile))
    context = {"agent_id": "agent-a", "correlation_id": "corr-1"}

    created = plugin.invoke(
        "local_record.create",
        {"kind": "task", "data": {"title": "写周报"}, "idempotency_key": "one"},
        context,
    )
    listed = plugin.invoke("local_record.list", {"kind": "task"}, context)

    assert listed["records"] == [created["record"]]
    assert created["source"] == "local"


def test_feishu_authority_does_not_fall_back_to_local(tmp_path: Path):
    profile = Profile.initialize("owner", home=tmp_path, authorities={"task": "feishu"})
    plugin = LocalRecordPlugin(LocalStore(profile))

    with pytest.raises(LocalRecordPluginError) as exc_info:
        plugin.invoke(
            "local_record.create",
            {"kind": "task", "data": {"title": "不能本地写"}},
            {"agent_id": "owner", "correlation_id": "corr-2"},
        )

    assert exc_info.value.error_code == "source_not_local"
