from __future__ import annotations

from pathlib import Path

import pytest

from integrations.base import AdapterError
from capability_plugins.knowledge import KnowledgePlugin, KnowledgePluginError
from knowledge_system.gateway import AgentPolicy, PermissionDenied
from knowledge_system.gateway.ima_service import ImaKnowledgeGateway, KnowledgeUnavailable


class FakeIma:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def search_items(self, knowledge_base_id: str, query: str, *, cursor: str = ""):
        self.calls.append((knowledge_base_id, query, cursor))
        return {"items": self.items, "next_cursor": "", "is_end": True}


def _gateway(tmp_path: Path, *, adapter, sensitivity: str = "level_0"):
    return ImaKnowledgeGateway(
        cache_path=tmp_path / "knowledge_cache.sqlite3",
        adapter=adapter,
        sources={"kb-one": {"domain": "general", "sensitivity": sensitivity}},
        policies={
            "agent-a": AgentPolicy(
                allowed_folders=("ima/kb-one",),
                allowed_domains=("general",),
                max_sensitivity="level_0",
            )
        },
        agent_credentials={"agent-a": "private-token"},
    )


def test_ima_gateway_filters_and_caches_only_authorized_summary(tmp_path: Path):
    adapter = FakeIma([
        {"media_id": "m1", "title": "睡眠", "introduction": "七小时睡眠摘要"},
    ])
    online = _gateway(tmp_path, adapter=adapter)

    result = online.query_knowledge("睡眠", agent_id="agent-a", credential="private-token")

    assert result.source == "ima"
    assert result.stale is False
    assert result.nodes[0].body == "七小时睡眠摘要"
    assert adapter.calls == [("kb-one", "睡眠", "")]

    offline = _gateway(tmp_path, adapter=None)
    cached = offline.query_knowledge("睡眠", agent_id="agent-a", credential="private-token")
    assert cached.source == "ima_cache"
    assert cached.stale is True
    assert cached.partial is True
    assert cached.cached_at
    assert cached.nodes[0].body == "七小时睡眠摘要"


def test_ima_gateway_does_not_cache_denied_sensitive_node(tmp_path: Path):
    gateway = _gateway(
        tmp_path,
        adapter=FakeIma([{"media_id": "secret", "title": "隐私", "introduction": "不可读摘要"}]),
        sensitivity="level_4",
    )

    result = gateway.query_knowledge("隐私", agent_id="agent-a", credential="private-token")
    assert result.nodes == []
    assert result.denied_count == 1

    with pytest.raises(KnowledgeUnavailable):
        _gateway(tmp_path, adapter=None).query_knowledge(
            "隐私", agent_id="agent-a", credential="private-token"
        )


def test_ima_gateway_skips_malformed_item_without_losing_valid_results(tmp_path: Path):
    gateway = _gateway(tmp_path, adapter=FakeIma([
        {"title": "没有 media_id 的损坏条目"},
        {"media_id": "good", "title": "有效", "introduction": "有效摘要"},
    ]))
    result = gateway.query_knowledge("有效", agent_id="agent-a", credential="private-token")
    assert [node.id for node in result.nodes] == ["ima:kb-one:good"]
    assert result.invalid_count == 1


def test_ima_gateway_rejects_wrong_agent_credential_before_lookup(tmp_path: Path):
    adapter = FakeIma([])
    gateway = _gateway(tmp_path, adapter=adapter)

    with pytest.raises(PermissionDenied):
        gateway.query_knowledge("x", agent_id="agent-a", credential="wrong")

    assert adapter.calls == []


def test_ima_gateway_classifies_auth_failure_without_leaking_response(tmp_path: Path):
    class Unauthorized:
        def search_items(self, *args, **kwargs):
            raise AdapterError("IMA 请求失败 HTTP 401 private body")

    gateway = _gateway(tmp_path, adapter=Unauthorized())
    with pytest.raises(KnowledgeUnavailable) as exc_info:
        gateway.query_knowledge("x", agent_id="agent-a", credential="private-token")

    assert exc_info.value.reason_code == "auth_required"
    assert "private body" not in str(exc_info.value)


def test_knowledge_plugin_reports_ima_cache_freshness_and_health(tmp_path: Path):
    _gateway(
        tmp_path,
        adapter=FakeIma([{"media_id": "m1", "title": "睡眠", "introduction": "授权摘要"}]),
    ).query_knowledge("睡眠", agent_id="agent-a", credential="private-token")
    plugin = KnowledgePlugin(_gateway(tmp_path, adapter=None), agent_id="agent-a", credential="private-token")

    result = plugin.invoke("knowledge.search", {"query": "睡眠"}, {})
    assert result["source"] == "ima_cache"
    assert result["stale"] is True
    assert result["partial"] is True
    assert result["cached_at"]
    assert result["warning"] == "结果可能不完整"
    assert plugin.invoke("knowledge.health", {}, {})["status"] == "offline_cache"

    with pytest.raises(KnowledgePluginError) as exc_info:
        plugin.invoke("knowledge.search", {"query": "不存在的查询"}, {})
    assert exc_info.value.code == "not_configured"


def test_ima_health_probe_distinguishes_online_and_auth_failure(tmp_path: Path):
    class Online(FakeIma):
        def list_items(self, knowledge_base_id: str, *, limit: int):
            assert knowledge_base_id == "kb-one"
            assert limit == 1
            return {"items": [], "is_end": True}

    class Unauthorized(FakeIma):
        def list_items(self, knowledge_base_id: str, *, limit: int):
            raise AdapterError("HTTP 401 private response")

    assert _gateway(tmp_path, adapter=Online([])).health(probe=True)["status"] == "online"
    failed = _gateway(tmp_path, adapter=Unauthorized([])).health(probe=True)
    assert failed["status"] == "auth_required"
    assert "private response" not in str(failed)


def test_cached_summary_is_denied_after_source_becomes_sensitive(tmp_path: Path):
    _gateway(tmp_path, adapter=FakeIma([
        {"media_id": "m1", "title": "私人", "introduction": "旧授权摘要"},
    ])).query_knowledge("私人", agent_id="agent-a", credential="private-token")

    with pytest.raises(KnowledgeUnavailable):
        _gateway(tmp_path, adapter=None, sensitivity="level_4").query_knowledge(
            "私人", agent_id="agent-a", credential="private-token")


def test_ima_list_maps_authorized_items_and_get_fetches_note_without_caching_body(tmp_path: Path):
    class NoteIma(FakeIma):
        def list_items(self, knowledge_base_id: str, *, limit: int, cursor: str = ""):
            assert limit <= 50
            return {"items": self.items, "is_end": True, "next_cursor": ""}

        def fetch_media(self, media_id: str):
            assert media_id == "note-1"
            return {"media_type": 11, "notebook_ext_info": {"notebook_id": "doc-1"}}

        def media_target(self, result):
            return "note", "doc-1"

        def fetch_note_content(self, note_id: str):
            assert note_id == "doc-1"
            return "完整但不应缓存的正文"

    online = _gateway(tmp_path, adapter=NoteIma([
        {"media_id": "note-1", "title": "会议", "introduction": "可缓存摘要"},
    ]))
    listed = online.list_knowledge(agent_id="agent-a", credential="private-token")
    assert listed.nodes[0].id == "ima:kb-one:note-1"
    plugin = KnowledgePlugin(online, agent_id="agent-a", credential="private-token")
    assert plugin.invoke("knowledge.list", {}, {})["nodes"][0]["id"] == "ima:kb-one:note-1"
    assert plugin.invoke("knowledge.get", {"node_id": "ima:kb-one:note-1"}, {})["content"] == "完整但不应缓存的正文"
    fetched = online.get_node(listed.nodes[0].id, agent_id="agent-a", credential="private-token")
    assert fetched.nodes[0].body == "完整但不应缓存的正文"

    offline = _gateway(tmp_path, adapter=None)
    cached = offline.get_node(listed.nodes[0].id, agent_id="agent-a", credential="private-token")
    assert cached.nodes[0].body == "可缓存摘要"
    assert cached.stale is True


def test_ima_get_falls_back_to_authorized_summary_when_fetch_fails(tmp_path: Path):
    class Interrupted(FakeIma):
        def fetch_media(self, media_id: str):
            raise TimeoutError("temporary outage")

    gateway = _gateway(tmp_path, adapter=Interrupted([
        {"media_id": "m1", "title": "恢复", "introduction": "可缓存摘要"},
    ]))
    gateway.query_knowledge("恢复", agent_id="agent-a", credential="private-token")

    result = gateway.get_node("ima:kb-one:m1", agent_id="agent-a", credential="private-token")
    assert result.source == "ima_cache"
    assert result.stale and result.partial
    assert result.nodes[0].body == "可缓存摘要"


def test_ima_list_follows_cursor_without_exceeding_provider_limit(tmp_path: Path):
    class Paged(FakeIma):
        def list_items(self, knowledge_base_id: str, *, limit: int, cursor: str = ""):
            assert limit == 50
            if not cursor:
                return {"items": [{"media_id": "m1", "title": "一", "introduction": "摘要一"}],
                        "is_end": False, "next_cursor": "page-2"}
            assert cursor == "page-2"
            return {"items": [{"media_id": "m2", "title": "二", "introduction": "摘要二"}],
                    "is_end": True, "next_cursor": ""}

    result = _gateway(tmp_path, adapter=Paged([])).list_knowledge(
        agent_id="agent-a", credential="private-token")
    assert [node.id for node in result.nodes] == ["ima:kb-one:m1", "ima:kb-one:m2"]
    assert result.partial is False
