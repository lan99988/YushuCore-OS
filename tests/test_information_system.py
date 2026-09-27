"""信息层测试：Schema / 信息对象库 / IMA 适配器 / 识别引擎 / 领域观察区。

覆盖实施设计 F2~F7。全部离线，不需要凭证与网络。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PROJECT_ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "00_信息层（Information）"

KNOWN_DOMAINS = ("工作", "学习", "生活", "阅读", "AI")

UNKNOWN_TEXT = (
    "这个飞盘组局的步骤是：先定场地，再约人，最后定规则。"
    "我实测下来，先定规则比先约人省事得多，避免临时改规则引发争执。"
    "这周要再跑一遍，把流程写清楚。"
)


# --------------------------------------------------------------------- 夹具


def _store(tmp_path: Path):
    from information_system.store import InformationStore

    store = InformationStore(tmp_path / "info.db")
    store.init_schema()
    return store


def _object(index: int, *, title: str = "标题", text: str = "正文"):
    from information_system.models import InformationObject, content_digest

    return InformationObject(
        source="manual",
        title=title,
        source_ref=f"case-{index}",
        content_digest=content_digest(text),
    )


# ------------------------------------------------------------------ Schema


@pytest.mark.parametrize("filename", ["InformationObject.json", "DomainRegistry.json"])
def test_information_schema_is_parseable_and_declares_invariants(filename: str):
    payload = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    assert payload["model"]
    assert payload["fields"]
    assert payload["invariants"]


def test_domain_registry_forbids_hardcoded_domain_enum():
    payload = json.loads((SCHEMA_DIR / "DomainRegistry.json").read_text(encoding="utf-8"))
    fields = {item["name"]: item for item in payload["fields"]}
    assert fields["state"]["options"] == [
        "observation",
        "candidate",
        "confirmed",
        "rejected",
        "merged",
        "archived",
    ]
    layer_names = [item["name"] for item in payload["topic_observation_fields"]]
    assert "layers" in layer_names
    joined = " ".join(payload["invariants"])
    assert "不得出现硬编码领域列表" in joined


# --------------------------------------------------------------- 信息对象库


def test_store_upsert_is_idempotent(tmp_path: Path):
    store = _store(tmp_path)
    obj = _object(1)
    first_id, first_created = store.upsert_object(obj)
    second_id, second_created = store.upsert_object(obj)
    assert first_created is True
    assert second_created is False
    assert first_id == second_id
    assert store.count() == 1
    assert store.find_by_source_key(obj.source_key)["object_id"] == first_id


def test_store_records_append_only_event_history(tmp_path: Path):
    store = _store(tmp_path)
    object_id, _ = store.upsert_object(_object(2))
    store.set_lifecycle(object_id, "inbox")
    store.set_lifecycle(object_id, "processing")
    events = [item["event_type"] for item in store.history(object_id)]
    assert events == ["captured", "lifecycle", "lifecycle"]
    assert [item["seq"] for item in store.history(object_id)] == [1, 2, 3]


def test_store_rejects_illegal_lifecycle_transition(tmp_path: Path):
    store = _store(tmp_path)
    object_id, _ = store.upsert_object(_object(3))
    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        store.set_lifecycle(object_id, "knowledge")


def test_store_confirmation_requires_reviewer(tmp_path: Path):
    from information_system.models import InformationObject

    store = _store(tmp_path)
    object_id, _ = store.upsert_object(_object(4, title="未确认对象"))
    with pytest.raises(ValueError, match="reviewer is required"):
        store.confirm_object(object_id, reviewer="  ")
    assert store.confirm_object(object_id, reviewer="蓝") == "confirmed"
    assert store.get(object_id)["decision_state"] == "confirmed"

    with pytest.raises(ValueError):
        InformationObject(source="manual", title="x", decision_state="confirmed")


def test_store_tombstone_archives_without_deleting(tmp_path: Path):
    store = _store(tmp_path)
    object_id, _ = store.upsert_object(_object(5))
    store.tombstone(object_id, reason="用户判定为噪声")
    assert store.get(object_id)["status"] == "archived"
    assert store.count() == 1
    assert store.history(object_id)[-1]["event_type"] == "tombstoned"
    with pytest.raises(ValueError, match="tombstone reason is required"):
        store.tombstone(object_id, reason=" ")


def test_store_keeps_recognition_reports(tmp_path: Path):
    from information_system.recognition import RecognitionEngine

    store = _store(tmp_path)
    obj = _object(6, title="408 复习方法", text="考研 408 的复习方法：先过教材再刷真题。")
    object_id, _ = store.upsert_object(obj)
    report = RecognitionEngine().recognize(obj, "考研 408 的复习方法：先过教材再刷真题。", known_domains=KNOWN_DOMAINS)
    store.record_report(report)
    latest = store.latest_report(object_id)
    assert latest["recognition"]["backend"] == "rule_based_v1"
    assert latest["recognition"]["recommendation"]["action"]


# ------------------------------------------------------------ 领域状态机


def test_domain_state_machine_blocks_skipping_candidate():
    from information_system.models import DomainRecord

    with pytest.raises(ValueError, match="illegal domain transition"):
        DomainRecord(name="新域", state="observation").transition("confirmed", actor="蓝")

    record = DomainRecord(name="新域", state="observation").transition("candidate")
    confirmed = record.transition("confirmed", actor="蓝", at="2026-09-14T00:00:00+08:00")
    assert confirmed.state == "confirmed"
    assert confirmed.confirmed_by == "蓝"

    with pytest.raises(ValueError, match="requires an actor"):
        DomainRecord(name="新域", state="candidate").transition("confirmed")


def test_domain_transition_via_store_rejects_skip(tmp_path: Path):
    from information_system.models import DomainRecord

    store = _store(tmp_path)
    store.upsert_domain(DomainRecord(name="观察域", state="observation"))
    with pytest.raises(ValueError, match="illegal domain transition"):
        store.transition_domain("观察域", "confirmed", actor="蓝")
    assert store.transition_domain("观察域", "candidate") == "candidate"
    assert store.transition_domain("观察域", "confirmed", actor="蓝") == "confirmed"
    assert store.get_domain("观察域")["confirmed_by"] == "蓝"


def test_merge_domain_migrates_object_ownership(tmp_path: Path):
    from information_system.models import DomainRecord, InformationObject

    store = _store(tmp_path)
    store.upsert_domain(DomainRecord(name="甲域", state="observation"))
    store.upsert_domain(DomainRecord(name="乙域", state="observation"))
    store.upsert_object(
        InformationObject(source="manual", title="归属对象", source_ref="merge-1", domains=("甲域",))
    )
    store.merge_domains("甲域", "乙域", actor="蓝")
    assert store.domain_object_count("乙域") == 1
    assert store.get_domain("甲域")["state"] == "merged"
    assert store.get_domain("甲域")["merged_into"] == store.get_domain("乙域")["domain_id"]


# ------------------------------------------------------------- IMA 适配器


class FakeTransport:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        return self.responses.get(path, {})


def _adapter(responses: dict[str, dict] | None = None, *, mode: str = "ASSIST"):
    from integrations.ima import ImaAdapter

    transport = FakeTransport(responses or {})
    return ImaAdapter(transport=transport, network_mode=mode), transport


def test_ima_config_declares_named_exception_not_global_switch():
    from integrations.settings import global_network_mode, resolve_network_mode

    assert global_network_mode() == "OFF"
    assert resolve_network_mode("ima") == "assist"
    assert resolve_network_mode("unknown-adapter") == "OFF"


def test_ima_adapter_refuses_network_when_gate_is_off():
    from integrations.base import AdapterError

    adapter, transport = _adapter(mode="OFF")
    with pytest.raises(AdapterError, match="requires ASSIST or SYNC"):
        adapter.list_items("kb-1")
    assert transport.calls == []


def test_ima_list_items_sends_declared_shape_and_parses_items():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["get_knowledge_list"]
    adapter, transport = _adapter(
        {
            path: {
                "knowledge_list": [
                    {"media_id": "m-1", "title": "条目一", "media_state": 2, "parse_progress": 100},
                    {"media_id": "m-2", "title": "条目二", "media_state": 1, "parse_progress": 30},
                ],
                "next_cursor": "c-2",
                "is_end": False,
            }
        }
    )
    result = adapter.list_items("kb-1", limit=20)
    assert [item["media_id"] for item in result["items"]] == ["m-1", "m-2"]
    assert result["next_cursor"] == "c-2"

    sent_path, payload = transport.calls[0]
    assert sent_path == path
    assert payload["knowledge_base_id"] == "kb-1"
    assert payload["limit"] == 20
    assert adapter.is_parsed(result["items"][0]) is True
    assert adapter.parse_progress(result["items"][1]) == 30


def test_ima_fetch_note_content_raises_when_body_missing():
    from integrations.base import AdapterError
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, _ = _adapter({DEFAULT_ENDPOINTS["note_get_doc_content"]: {"other": 1}})
    with pytest.raises(AdapterError, match="返回中无 content 字段"):
        adapter.fetch_note_content("n-1")


def test_ima_append_note_is_the_only_mutation_path():
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, transport = _adapter({DEFAULT_ENDPOINTS["note_append_doc"]: {"note_id": "n-1"}})
    adapter.append_note("n-1", "追加内容")
    _, payload = transport.calls[0]
    assert payload == {"note_id": "n-1", "content_format": 1, "content": "追加内容"}
    with pytest.raises(ValueError, match="note_id 不能为空"):
        adapter.append_note("  ", "x")
    with pytest.raises(ValueError, match="追加内容不能为空"):
        adapter.append_note("n-1", "   ")


def test_ima_unavailable_capabilities_raise_explicitly():
    """delete / update 是**平台边界**，不是未实现（2026-09-15 真实探测定案）。"""
    from integrations.ima import ImaCapabilityError

    adapter, transport = _adapter()
    for method in ("delete_item", "update_item"):
        with pytest.raises(ImaCapabilityError):
            getattr(adapter, method)("x")
    assert transport.calls == []


def test_ima_import_urls_enforces_batch_limit():
    from integrations.ima import DEFAULT_ENDPOINTS, IMPORT_URLS_BATCH_LIMIT

    adapter, transport = _adapter(
        {
            DEFAULT_ENDPOINTS["get_knowledge_list"]: {"current_path": [{"folder_id": "root-1"}]},
            DEFAULT_ENDPOINTS["import_urls"]: {},
        }
    )
    adapter.import_urls("kb-1", [f"https://example.com/{i}" for i in range(IMPORT_URLS_BATCH_LIMIT)])
    assert len(transport.calls[1][1]["urls"]) == IMPORT_URLS_BATCH_LIMIT
    with pytest.raises(ValueError, match="单次最多导入"):
        adapter.import_urls("kb-1", [f"https://example.com/{i}" for i in range(IMPORT_URLS_BATCH_LIMIT + 1)])
    with pytest.raises(ValueError, match="urls 不能为空"):
        adapter.import_urls("kb-1", ["  "])


def test_ima_create_media_rejects_unknown_extension(tmp_path: Path):
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, transport = _adapter({DEFAULT_ENDPOINTS["create_media"]: {}})
    good = tmp_path / "note.md"
    good.write_text("x", encoding="utf-8")
    adapter.create_media(file_path=good, knowledge_base_id="kb-1")
    assert transport.calls[0][1]["content_type"] == "text/markdown"

    weird = tmp_path / "note.zzz"
    weird.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的扩展名"):
        adapter.create_media(file_path=weird, knowledge_base_id="kb-1")
    with pytest.raises(ValueError, match="文件不存在"):
        adapter.create_media(file_path=tmp_path / "missing.md", knowledge_base_id="kb-1")


def test_ima_event_and_tombstone_are_append_only_text():
    from integrations.ima import ImaAdapter

    text = ImaAdapter.build_event_append("条目一", "已确认", "转为认知原则", at="2026-09-14T10:00:00+08:00")
    assert text.startswith("\n## [2026-09-14T10:00:00+08:00] 已确认")
    assert "- 对象：条目一" in text
    assert "- 说明：转为认知原则" in text
    assert "[DELETED]" in ImaAdapter.build_tombstone("条目一", "噪声", at="2026-09-14T10:00:00+08:00")
    with pytest.raises(ValueError, match="event 不能为空"):
        ImaAdapter.build_event_append("条目一", "   ", "x", at="2026-09-14T10:00:00+08:00")


def test_ima_pulled_item_requires_media_id_and_maps_to_capture_contract():
    from integrations.base import AdapterError
    from integrations.ima import PulledItem

    with pytest.raises(AdapterError, match="缺少 media_id"):
        PulledItem.from_api({"title": "无 ID"})

    item = PulledItem.from_api({"media_id": "m-9", "title": "标题", "introduction": "摘要"})
    captured = item.to_capture()
    assert captured == {
        "source": "ima",
        "title": "标题",
        "content": "摘要",
        "source_ref": "m-9",
        "source_container": "",
    }


def test_ima_credentials_missing_raises_without_silent_fallback(monkeypatch, tmp_path: Path):
    from integrations import settings

    monkeypatch.delenv(settings.IMA_CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(settings.IMA_API_KEY_ENV, raising=False)
    monkeypatch.setattr(settings, "IMA_LOCAL_CONFIG", tmp_path / "absent.yaml")
    with pytest.raises(settings.IntegrationConfigError, match="缺少 IMA 凭证"):
        settings.ima_credentials()

    monkeypatch.setenv(settings.IMA_CLIENT_ID_ENV, "cid")
    monkeypatch.setenv(settings.IMA_API_KEY_ENV, "key")
    assert settings.ima_credentials() == ("cid", "key")


# ------------------------ IMA 端点对齐官方（2026-09-14 真实账号验证结果固化）


def test_ima_endpoint_paths_match_official_docs():
    """端点路径以官方 skill 包 + 真实账号双向验证为准。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    assert DEFAULT_ENDPOINTS["note_list_note"] == "/openapi/note/v1/list_note"
    assert DEFAULT_ENDPOINTS["note_list_notebook"] == "/openapi/note/v1/list_notebook"
    assert DEFAULT_ENDPOINTS["note_search_note"] == "/openapi/note/v1/search_note"
    assert DEFAULT_ENDPOINTS["note_get_doc_content"] == "/openapi/note/v1/get_doc_content"
    assert DEFAULT_ENDPOINTS["check_repeated_names"] == "/openapi/wiki/v1/check_repeated_names"
    assert DEFAULT_ENDPOINTS["get_knowledge_base"] == "/openapi/wiki/v1/get_knowledge_base"
    # `/openapi/note/v1/list_docs` 实测 HTTP 404，属早期误推断，不得复活
    assert not any(v.endswith("/list_docs") for v in DEFAULT_ENDPOINTS.values())


def test_ima_search_knowledge_bases_reads_info_list_with_kb_fields():
    """真实响应是 info_list，条目字段为 kb_id / kb_name（官方 api.md 写作 id / name，文档有误）。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["search_knowledge_base"]
    adapter, transport = _adapter(
        {
            path: {
                "info_list": [
                    {"kb_id": "kb-1", "kb_name": "知识库一", "member_count": "1", "content_count": "9"}
                ],
                "is_end": True,
                "next_cursor": "",
            }
        }
    )
    found = adapter.search_knowledge_bases("", limit=20)
    assert [b["kb_id"] for b in found] == ["kb-1"]
    assert transport.calls[0][1] == {"query": "", "cursor": "", "limit": 20}

    with pytest.raises(ValueError, match="越界"):
        adapter.search_knowledge_bases("", limit=21)


def test_ima_search_items_reads_info_list():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["search_knowledge"]
    adapter, transport = _adapter(
        {path: {"info_list": [{"media_id": "m-1", "title": "命中"}], "is_end": False, "next_cursor": "c-2"}}
    )
    result = adapter.search_items("kb-1", "关键词")
    assert [item["media_id"] for item in result["items"]] == ["m-1"]
    assert result["next_cursor"] == "c-2"
    assert transport.calls[0][1] == {"knowledge_base_id": "kb-1", "query": "关键词", "cursor": ""}


def test_ima_get_knowledge_base_validates_ids():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["get_knowledge_base"]
    adapter, transport = _adapter({path: {"infos": {"kb-1": {"id": "kb-1", "name": "一"}}}})
    result = adapter.get_knowledge_base(["kb-1"])
    assert result["infos"]["kb-1"]["name"] == "一"
    assert transport.calls[0][1] == {"ids": ["kb-1"]}

    with pytest.raises(ValueError, match="不能为空"):
        adapter.get_knowledge_base([])
    with pytest.raises(ValueError, match="重复"):
        adapter.get_knowledge_base(["kb-1", "kb-1"])
    with pytest.raises(ValueError, match="最多 20"):
        adapter.get_knowledge_base([f"kb-{i}" for i in range(21)])


def test_ima_check_repeated_names_shape_and_parse():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["check_repeated_names"]
    adapter, transport = _adapter({path: {"results": [{"name": "a.pdf", "is_repeated": True}]}})
    out = adapter.check_repeated_names(
        knowledge_base_id="kb-1", params=[{"name": "a.pdf", "media_type": 1}]
    )
    assert out == [{"name": "a.pdf", "is_repeated": True}]
    assert transport.calls[0][1] == {
        "params": [{"name": "a.pdf", "media_type": 1}],
        "knowledge_base_id": "kb-1",
    }

    with pytest.raises(ValueError, match="非空 name"):
        adapter.check_repeated_names(knowledge_base_id="kb-1", params=[{"media_type": 1}])
    with pytest.raises(ValueError, match="media_type 必须是整数"):
        adapter.check_repeated_names(knowledge_base_id="kb-1", params=[{"name": "a", "media_type": "1"}])
    with pytest.raises(ValueError, match="params 不能为空"):
        adapter.check_repeated_names(knowledge_base_id="kb-1", params=[])


def test_ima_list_notebooks_cursor_starts_at_zero():
    """官方明确：笔记本列表首屏游标是 "0"，不是空串（与其它翻页接口不同）。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_list_notebook"]
    adapter, transport = _adapter(
        {path: {"note_folder_infos": [{"folder_id": "f-1", "name": "笔记本一"}], "is_end": True}}
    )
    result = adapter.list_notebooks()
    assert [f["folder_id"] for f in result["items"]] == ["f-1"]
    assert transport.calls[0][1]["cursor"] == "0"


def test_ima_list_notes_parses_note_book_list():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_list_note"]
    adapter, transport = _adapter(
        {path: {"note_book_list": [{"note_id": "n-1", "title": "笔记一"}], "is_end": True}}
    )
    result = adapter.list_notes()
    assert [n["note_id"] for n in result["items"]] == ["n-1"]
    assert transport.calls[0][1]["limit"] == 20


def test_ima_search_notes_always_sends_query_info():
    """实测：缺 query_info 时服务端返回 100001；官方文档标为可选，与实现不符。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_search_note"]
    adapter, transport = _adapter(
        {path: {"search_note_infos": [{"note_book_info": {"note_id": "n-1"}}], "total_hit_num": 1}}
    )
    result = adapter.search_notes(title="ima", start=0, end=5)
    assert result["items"][0]["note_book_info"]["note_id"] == "n-1"
    assert result["total_hit_num"] == 1

    _, payload = transport.calls[0]
    assert payload["query_info"] == {"title": "ima", "content": ""}
    assert (payload["start"], payload["end"]) == (0, 5)

    with pytest.raises(ValueError, match="不得超过"):
        adapter.search_notes(end=30)
    with pytest.raises(ValueError, match="翻页区间非法"):
        adapter.search_notes(start=5, end=5)


def test_ima_fetch_note_content_sends_target_content_format():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_get_doc_content"]
    adapter, transport = _adapter({path: {"content": "正文"}})
    assert adapter.fetch_note_content("n-1") == "正文"
    assert transport.calls[0][1] == {"note_id": "n-1", "target_content_format": 0}

    with pytest.raises(ValueError, match="只支持"):
        adapter.fetch_note_content("n-1", target_content_format=1)


def test_ima_import_urls_resolves_real_root_folder():
    """⚠️ 官方文档称「根目录 folder_id == knowledge_base_id」——实测错误（返回 222000）。

    真实根目录来自 get_knowledge_list 的 current_path[0].folder_id。
    """
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, transport = _adapter(
        {
            DEFAULT_ENDPOINTS["get_knowledge_list"]: {
                "knowledge_list": [],
                "current_path": [{"folder_id": "root-real-id", "name": "库"}],
                "is_end": True,
            },
            DEFAULT_ENDPOINTS["import_urls"]: {},
        }
    )
    adapter.import_urls("kb-1", ["https://example.com/a"])
    assert [path for path, _ in transport.calls] == [
        DEFAULT_ENDPOINTS["get_knowledge_list"],
        DEFAULT_ENDPOINTS["import_urls"],
    ]
    assert transport.calls[1][1]["folder_id"] == "root-real-id"
    assert transport.calls[1][1]["folder_id"] != "kb-1"

    adapter.import_urls("kb-1", ["https://example.com/b"], folder_id="folder-9")
    assert transport.calls[2][1]["folder_id"] == "folder-9"


def test_ima_root_folder_id_raises_without_current_path():
    from integrations.base import AdapterError
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, _ = _adapter({DEFAULT_ENDPOINTS["get_knowledge_list"]: {"knowledge_list": []}})
    with pytest.raises(AdapterError, match="无法取得根目录 folder_id"):
        adapter.root_folder_id("kb-1")


# --------------- 未文档化端点（2026-09-15 真实探测发现，均已实测或已定案）


def test_ima_endpoint_table_marks_undocumented_routes():
    from integrations.ima import DEFAULT_ENDPOINTS

    for key in ("create_folder", "rename_knowledge", "move_knowledge", "create_knowledge_base"):
        assert key in DEFAULT_ENDPOINTS
    # 删除类端点必须**不存在**（14 条候选路径实测全 404）
    joined = " ".join(DEFAULT_ENDPOINTS.values())
    assert "delete" not in joined
    assert "remove" not in joined
    assert "trash" not in joined


def test_ima_create_folder_returns_media_id_not_folder_id():
    """未文档化端点；实测成功。文件夹也以 media_id（folder_ 前缀）标识。

    父目录的**线上字段名是 `folder_id`**：`parent_folder_id` 会被服务端静默忽略
    （2026-09-15 类型预言机实测），导致子文件夹悄悄落到根目录。
    """
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["create_folder"]
    adapter, transport = _adapter({path: {"media_id": "folder_123"}})
    result = adapter.create_folder(knowledge_base_id="kb-1", name="新文件夹")
    assert result["media_id"] == "folder_123"
    assert transport.calls[0][1] == {"knowledge_base_id": "kb-1", "name": "新文件夹"}

    adapter.create_folder(knowledge_base_id="kb-1", name="子夹", parent_folder_id="folder_123")
    assert transport.calls[1][1]["folder_id"] == "folder_123"
    assert "parent_folder_id" not in transport.calls[1][1]  # 绝不能发出被忽略的旧字段名

    with pytest.raises(ValueError, match="不能为空"):
        adapter.create_folder(knowledge_base_id="kb-1", name="   ")
    with pytest.raises(ValueError, match="255"):
        adapter.create_folder(knowledge_base_id="kb-1", name="x" * 256)


def test_ima_create_note_has_no_folder_name_and_note_folders_cannot_be_created():
    """`folder_name` 实测被服务端静默忽略 → 参数已移除。

    撞名预言机（用**已存在**的笔记本名）不报 `210030`，用全新名字也不建笔记本。

    ⚠️ 但「不能建笔记本」这个说法**只对 `import_doc` 成立**：
    2026-09-15 后续探测发现存在未文档化端点 `add_notebook`，见下一个测试。
    """
    import inspect

    from integrations.ima import DEFAULT_ENDPOINTS, ImaAdapter

    sig = inspect.signature(ImaAdapter.create_note)
    assert "folder_name" not in sig.parameters, "folder_name 实测无效，不应保留在签名里"

    path = DEFAULT_ENDPOINTS["note_import_doc"]
    adapter, transport = _adapter({path: {"note_id": "n-1"}})
    adapter.create_note("# 标题\n\n正文", folder_id="nb-1")
    sent = transport.calls[0][1]
    assert sent["folder_id"] == "nb-1"
    assert "folder_name" not in sent


def test_ima_add_notebook_uses_folder_name_not_name_and_is_flat():
    """`add_notebook` 是未文档化端点；**名字段叫 `folder_name`，不叫 `name`**。

    用 `name` 会报 `100001 文件名不能为空`（极具误导性，本次探测踩过）。
    笔记本是**扁平**的：`parent_folder_id` 在响应里存在但输入不认。
    """
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_add_notebook"]
    assert path == "/openapi/note/v1/add_notebook"
    adapter, transport = _adapter({path: {"folder_id": "folderabc", "folder_name": "新笔记本"}})

    result = adapter.add_notebook(folder_name="新笔记本")
    assert result["folder_id"] == "folderabc"
    assert transport.calls[0][1] == {"folder_name": "新笔记本"}
    assert "name" not in transport.calls[0][1]

    with pytest.raises(ValueError, match="笔记本名不能为空"):
        adapter.add_notebook(folder_name="   ")


def test_ima_rename_notebook_refuses_empty_new_name():
    """`rename_notebook` 的名字段是 `new_folder_name`；**不带新名会把名字清空**。

    实测：只传 `folder_id` 返 `code=0 success`，但笔记本名字变成空串
    （15 个候选字段穷举后才定位到 `new_folder_name`）。
    → 适配器必须拒绝空新名，避免把用户笔记本名字抹掉。
    """
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_rename_notebook"]
    adapter, transport = _adapter({path: {}})

    adapter.rename_notebook(folder_id="folderabc", new_name="新名字")
    assert transport.calls[0][1] == {"folder_id": "folderabc", "new_folder_name": "新名字"}
    assert "folder_name" not in transport.calls[0][1]  # 旧猜的字段名，实测不认
    assert "name" not in transport.calls[0][1]

    with pytest.raises(ValueError, match="清空"):
        adapter.rename_notebook(folder_id="folderabc", new_name="  ")
    with pytest.raises(ValueError, match="folder_id 不能为空"):
        adapter.rename_notebook(folder_id="  ", new_name="x")
    assert len(transport.calls) == 1, "空新名必须被拦下，绝不能发出去"


def test_ima_rename_note_changes_title_in_place():
    """`rename_note` 是未文档化端点；字段 `note_id` + `title`，原地改标题。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["note_rename_note"]
    assert path == "/openapi/note/v1/rename_note"
    adapter, transport = _adapter({path: {"note_id": "n-1"}})

    adapter.rename_note(note_id="n-1", title="IMSDEL-20260915a3f9-标题")
    assert transport.calls[0][1] == {"note_id": "n-1", "title": "IMSDEL-20260915a3f9-标题"}

    with pytest.raises(ValueError, match="note_id 不能为空"):
        adapter.rename_note(note_id=" ", title="x")
    with pytest.raises(ValueError, match="title 不能为空"):
        adapter.rename_note(note_id="n-1", title=" ")


def test_ima_mount_note_into_knowledge_uses_media_type_11():
    """把笔记挂进知识库**文件夹路径**：`add_knowledge` + `media_type=11` + `note_info`。

    这是「让每篇笔记落到知识库某个路径下」的关键手段；实测回读
    `current_path` 深度 3 正确。
    """
    from integrations.ima import DEFAULT_ENDPOINTS, MEDIA_TYPE_NOTE

    assert MEDIA_TYPE_NOTE == 11
    path = DEFAULT_ENDPOINTS["add_knowledge"]
    adapter, transport = _adapter({path: {"media_id": "note_xxx"}})

    adapter.mount_note_into_knowledge(
        knowledge_base_id="kb-1", note_id="n-9", title="标题", folder_id="folder_deep"
    )
    sent = transport.calls[0][1]
    assert sent["media_type"] == 11
    assert sent["note_info"] == {"content_id": "n-9"}
    assert sent["folder_id"] == "folder_deep"
    assert sent["knowledge_base_id"] == "kb-1"

    # 不传 folder_id 时挂到根目录（不下发该字段）
    adapter.mount_note_into_knowledge(knowledge_base_id="kb-1", note_id="n-9", title="标题")
    assert "folder_id" not in transport.calls[1][1]

    with pytest.raises(ValueError, match="knowledge_base_id 不能为空"):
        adapter.mount_note_into_knowledge(knowledge_base_id=" ", note_id="n-9", title="t")
    with pytest.raises(ValueError, match="note_id 不能为空"):
        adapter.mount_note_into_knowledge(knowledge_base_id="kb-1", note_id=" ", title="t")


def test_ima_deletion_mark_is_search_safe_and_idempotent():
    """「待删」标记：只用字母/数字/连字符，且重复打标不叠加。"""
    from integrations.ima import DELETION_MARKER, ImaAdapter

    batch = ImaAdapter.new_deletion_batch(at=datetime(2026, 9, 15, 12, 0, 0))
    assert re.fullmatch(r"20260915[0-9a-f]{4}", batch), batch

    marked = ImaAdapter.build_marked_title("原标题", batch=batch)
    assert marked == f"{DELETION_MARKER}-{batch}-原标题"
    assert ImaAdapter.is_marked_title(marked)
    assert ImaAdapter.strip_mark(marked) == "原标题"
    assert not ImaAdapter.is_marked_title("原标题")

    # 幂等：对已打标的标题再打一次，只替换批次，不叠加
    again = ImaAdapter.build_marked_title(marked, batch="20260915dead")
    assert again.count(DELETION_MARKER) == 1
    assert again == "IMSDEL-20260915dead-原标题"
    assert ImaAdapter.strip_mark(again) == "原标题"

    # 标记不得含括号类符号（客户端搜索行为未实测，刻意回避）
    assert not re.search(r"[\[\]（）()【】〔〕]", marked)

    with pytest.raises(ValueError, match="批次号格式非法"):
        ImaAdapter.build_marked_title("x", batch="bad")
    with pytest.raises(ValueError, match="原标题不能为空"):
        ImaAdapter.build_marked_title("   ", batch=batch)


def test_ima_mark_and_unmark_for_deletion_rename_in_place():
    """打标/撤标都走 rename_knowledge —— API 侧唯一可用的「改」。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["rename_knowledge"]
    adapter, transport = _adapter({path: {"ret_code": 0}})

    adapter.mark_for_deletion(
        knowledge_base_id="kb-1", media_id="m-1", title="旧标题", batch="20260915a3f9"
    )
    assert transport.calls[0][1] == {
        "knowledge_base_id": "kb-1",
        "media_id": "m-1",
        "name": "IMSDEL-20260915a3f9-旧标题",
    }

    adapter.unmark_for_deletion(
        knowledge_base_id="kb-1", media_id="m-1", title="IMSDEL-20260915a3f9-旧标题"
    )
    assert transport.calls[1][1]["name"] == "旧标题"


def test_ima_rename_knowledge_is_the_only_in_place_update():
    """未文档化端点；2026-09-15 实测成功 —— 官方 API 中唯一的原地「改」。"""
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["rename_knowledge"]
    adapter, transport = _adapter({path: {}})
    adapter.rename_knowledge(knowledge_base_id="kb-1", media_id="folder_123", name="改名后")
    assert transport.calls[0][1] == {
        "knowledge_base_id": "kb-1",
        "media_id": "folder_123",
        "name": "改名后",
    }

    with pytest.raises(ValueError, match="media_id 不能为空"):
        adapter.rename_knowledge(knowledge_base_id="kb-1", media_id="  ", name="x")
    with pytest.raises(ValueError, match="不得超过 255"):
        adapter.rename_knowledge(knowledge_base_id="kb-1", media_id="m", name="x" * 256)


def test_ima_move_knowledge_fails_loudly_when_nothing_selected():
    """move_knowledge 的字段名/元素形状/src≠dst 均已实测排除，move_results 仍恒为空
    → 疑为服务端空壳接口。必须显式报错，绝不允许静默无效。"""
    from integrations.base import AdapterError
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["move_knowledge"]
    adapter, _ = _adapter({path: {"move_results": {}}})
    with pytest.raises(AdapterError, match="空壳"):
        adapter.move_knowledge(src_knowledge_base_id="kb-1", dst_knowledge_base_id="kb-2")

    ok_adapter, ok_transport = _adapter({path: {"move_results": {"folder_1": {"ret_code": 0}}}})
    result = ok_adapter.move_knowledge(
        src_knowledge_base_id="kb-1", dst_knowledge_base_id="kb-2", media_ids=["folder_1"]
    )
    assert result["move_results"]
    assert ok_transport.calls[0][1]["src_knowledge_base_id"] == "kb-1"

    with pytest.raises(ValueError, match="不能为空"):
        ok_adapter.move_knowledge(src_knowledge_base_id="  ", dst_knowledge_base_id="kb-2")


def test_ima_create_knowledge_base_requires_name_and_type():
    """未文档化端点，2026-09-15 端到端验证成功——必填字段是 **两个**。

    服务端校验一次只报第一个不合格字段，早期只探明 `name`；
    只传 name 会得到
    `code=51 invalid CreateKnowledgeBaseReq.Type: value must be in list [...]`。
    """
    from integrations.ima import DEFAULT_ENDPOINTS, KB_TYPES

    adapter, transport = _adapter({DEFAULT_ENDPOINTS["create_knowledge_base"]: {"id": "kb-new"}})
    adapter.create_knowledge_base(name="新库")
    assert transport.calls[0][1] == {"name": "新库", "type": "KBT_MINE_KB"}

    adapter.create_knowledge_base(name=" 新库 ", kb_type="KBT_SHARED_KB")
    assert transport.calls[1][1] == {"name": "新库", "type": "KBT_SHARED_KB"}

    with pytest.raises(ValueError, match="不能为空"):
        adapter.create_knowledge_base(name="   ")
    with pytest.raises(ValueError, match="不得超过 25"):
        adapter.create_knowledge_base(name="x" * 26)
    with pytest.raises(ValueError, match="kb_type 必须是"):
        adapter.create_knowledge_base(name="新库", kb_type="KBT_NOT_A_REAL_TYPE")

    assert KB_TYPES == frozenset(
        {"KBT_MINE_KB", "KBT_SHARED_KB", "KBT_SUBSCRIBED_CREATE_KB"}
    )


def test_ima_add_knowledge_omits_unofficial_duplicate_strategy():
    """duplicate_name_strategy 不在官方参数表内 → 默认不发送。"""
    from integrations.ima import DEFAULT_ENDPOINTS, MEDIA_TYPE_MARKDOWN

    adapter, transport = _adapter({DEFAULT_ENDPOINTS["add_knowledge"]: {"media_id": "m-1"}})
    adapter.add_knowledge(knowledge_base_id="kb-1", title="标题")
    payload = transport.calls[0][1]
    assert "duplicate_name_strategy" not in payload
    assert payload == {"knowledge_base_id": "kb-1", "title": "标题", "media_type": MEDIA_TYPE_MARKDOWN}

    with pytest.raises(ValueError, match="必须提供 web_info"):
        adapter.add_knowledge(knowledge_base_id="kb-1", title="t", media_type=2)
    with pytest.raises(ValueError, match="title 不能为空"):
        adapter.add_knowledge(knowledge_base_id="kb-1", title="  ")


def test_ima_create_note_rejects_non_markdown():
    from integrations.ima import DEFAULT_ENDPOINTS

    adapter, _ = _adapter({DEFAULT_ENDPOINTS["note_import_doc"]: {"note_id": "n-1"}})
    with pytest.raises(ValueError, match="仅支持 content_format=1"):
        adapter.create_note("正文", content_format=0)


def test_ima_media_target_branches():
    """get_media_info 的三条分支：可下载 / 笔记类型 / 只能到客户端看。"""
    from integrations.ima import ImaAdapter

    url_info = {"url": "https://example.com/a.pdf", "headers": {"X-IMA-Platform": "H5"}}
    assert ImaAdapter.media_target({"media_type": 1, "url_info": url_info}) == ("url", url_info)
    assert ImaAdapter.media_target(
        {"media_type": 11, "notebook_ext_info": {"notebook_id": "nb-1"}}
    ) == ("note", "nb-1")
    assert ImaAdapter.media_target({"media_type": 1}) == ("client_only", None)


def test_ima_size_limits_match_official_table():
    from integrations.ima import (
        MEDIA_TYPE_AUDIO,
        MEDIA_TYPE_EPUB,
        MEDIA_TYPE_HTML,
        MEDIA_TYPE_IMAGE,
        MEDIA_TYPE_MARKDOWN,
        SIZE_LIMIT_10MB,
        SIZE_LIMIT_30MB,
        SIZE_LIMIT_50MB,
        size_limit_for,
    )

    for media_type in (MEDIA_TYPE_MARKDOWN, MEDIA_TYPE_HTML):
        assert size_limit_for(media_type) == SIZE_LIMIT_10MB
    assert size_limit_for(MEDIA_TYPE_IMAGE) == SIZE_LIMIT_30MB
    assert size_limit_for(MEDIA_TYPE_EPUB) == SIZE_LIMIT_50MB
    assert size_limit_for(MEDIA_TYPE_AUDIO) == 200 * 1024 * 1024


def test_ima_ext_maps_cover_official_media_types():
    from integrations.ima import (
        EXT_TO_MEDIA_TYPE,
        EXT_TO_MIME,
        MEDIA_TYPE_EPUB,
        MEDIA_TYPE_EXCEL,
        MEDIA_TYPE_HTML,
        MEDIA_TYPE_MARKDOWN,
        MEDIA_TYPE_VIDEO,
    )

    # 官方 16（视频解析）不支持经 skill 添加 → 不得出现在扩展名映射中
    assert MEDIA_TYPE_VIDEO not in set(EXT_TO_MEDIA_TYPE.values())
    # 每个可映射扩展名都必须有 MIME（两表不得脱节）
    assert set(EXT_TO_MEDIA_TYPE) <= set(EXT_TO_MIME)
    assert EXT_TO_MEDIA_TYPE["md"] == MEDIA_TYPE_MARKDOWN
    assert EXT_TO_MEDIA_TYPE["csv"] == MEDIA_TYPE_EXCEL
    assert EXT_TO_MEDIA_TYPE["epub"] == MEDIA_TYPE_EPUB
    assert EXT_TO_MEDIA_TYPE["htm"] == MEDIA_TYPE_HTML
    assert EXT_TO_MIME["htm"] == "text/html"


def test_ima_create_media_enforces_official_size_limit(tmp_path: Path):
    from integrations.ima import DEFAULT_ENDPOINTS, SIZE_LIMIT_10MB

    adapter, transport = _adapter({DEFAULT_ENDPOINTS["create_media"]: {}})
    big = tmp_path / "big.md"
    with open(big, "wb") as handle:
        handle.seek(SIZE_LIMIT_10MB + 1)
        handle.write(b"x")
    with pytest.raises(ValueError, match="超过官方大小上限"):
        adapter.create_media(file_path=big, knowledge_base_id="kb-1")
    assert transport.calls == []


def test_ima_list_items_exposes_current_path():
    from integrations.ima import DEFAULT_ENDPOINTS

    path = DEFAULT_ENDPOINTS["get_knowledge_list"]
    adapter, _ = _adapter(
        {
            path: {
                "knowledge_list": [{"media_id": "m-1", "title": "一"}],
                "current_path": [{"folder_id": "f-0", "name": "根"}],
                "is_end": True,
            }
        }
    )
    result = adapter.list_items("kb-1")
    assert result["current_path"] == [{"folder_id": "f-0", "name": "根"}]


# --------------------------------------------------------------- 识别引擎


def test_recognition_report_is_complete_and_governed():
    from information_system.recognition import RecognitionEngine

    text = (
        "和 AI 协作有一条铁律：永远先把上下文喂全，再让它动手。"
        "我意识到，模型能力的上限往往不是模型本身，而是我们给的上下文质量。"
        "下一步应该把这条原则写进工作流文档，以后一律先整理资料再开工。"
    )
    obj = _object(7, title="AI 协作原则", text=text)
    report = RecognitionEngine().recognize(obj, text, known_domains=KNOWN_DOMAINS)
    payload = report.to_dict()["recognition"]

    for key in ("temporal", "types", "knowledge_level", "cognitive_os", "domains",
                "concepts", "relations", "recommendation", "confidence", "evidence", "reason"):
        assert key in payload, key

    assert report.backend == "rule_based_v1"
    assert payload["recommendation"]["action"] == "needs_human_review"
    assert [item.name for item in report.domains][0] == "AI"
    assert report.actions


def test_recognition_never_emits_formal_knowledge_or_core_levels():
    from information_system.recognition import RecognitionEngine

    text = (
        "《运动神经元》这本书给了一条原则：绝不可以跳过基础。"
        "这是长期积累的方法，我复盘下来发现框架比技巧重要。"
    )
    obj = _object(8, title="原则摘录", text=text)
    report = RecognitionEngine().recognize(obj, text, known_domains=KNOWN_DOMAINS)
    assert report.knowledge_level in {"information", "knowledge_candidate"}
    assert report.cognitive_os_level.endswith("_candidate") or report.cognitive_os_level in {
        "none",
        "plain",
        "insight",
    }
    assert report.knowledge_level != "knowledge"


def test_recognition_marks_unknown_topic_instead_of_forcing_a_domain():
    from information_system.recognition import RecognitionEngine

    text = "今天下午在楼下咖啡店坐了会儿，天有点阴，回来路上看到一只很胖的橘猫。"
    obj = _object(9, title="随手记", text=text)
    report = RecognitionEngine().recognize(obj, text, known_domains=KNOWN_DOMAINS)
    assert report.domains == ()
    assert report.new_domain_detected is True
    assert report.observation_detected is True
    assert report.to_dict()["recognition"]["recommendation"]["action"] == "observe_unknown_topic"


def test_recognition_is_deterministic():
    from information_system.recognition import RecognitionEngine

    engine = RecognitionEngine()
    obj = _object(10, title="学习复习方法", text=UNKNOWN_TEXT)
    first = engine.recognize(obj, UNKNOWN_TEXT, known_domains=KNOWN_DOMAINS).to_dict()
    second = engine.recognize(obj, UNKNOWN_TEXT, known_domains=KNOWN_DOMAINS).to_dict()
    assert first == second


def test_recognition_engine_downgrades_backend_that_exceeds_knowledge_ceiling():
    from information_system.recognition import RecognitionEngine

    class RogueBackend:
        name = "rogue"

        def analyze(self, *, object_id, title, text, known_domains):
            return {"knowledge_level": "core_knowledge", "backend": "rogue"}

    report = RecognitionEngine(backend=RogueBackend()).recognize(
        _object(11), "x", known_domains=KNOWN_DOMAINS
    )
    assert report.knowledge_level == "knowledge_candidate"


# ------------------------------------------------------------- 领域观察区


def test_five_layer_verdicts_are_complete_and_explainable():
    from information_system.observation import FIVE_LAYERS, ObservationEngine, week_key
    from information_system.recognition import RecognitionEngine

    obj = _object(12, title="飞盘组局", text=UNKNOWN_TEXT)
    report = RecognitionEngine().recognize(obj, UNKNOWN_TEXT, known_domains=KNOWN_DOMAINS)
    layers = ObservationEngine().evaluate(report=report, text=UNKNOWN_TEXT)

    assert [item.layer for item in layers] == list(FIVE_LAYERS)
    for item in layers:
        assert 0.0 <= item.score <= 1.0
        assert item.reason.strip()
    overall = ObservationEngine.aggregate(layers)
    assert 0.0 <= overall <= 1.0
    assert week_key(datetime(2026, 9, 14, tzinfo=timezone.utc)) == "2026-W38"


def test_single_occurrence_topic_stays_in_observation():
    from information_system.observation import ObservationEngine

    engine = ObservationEngine()
    assert engine.decide_state(overall=0.95, evidence_count=1) == "observation"
    assert engine.decide_state(overall=0.95, evidence_count=2) == "candidate"
    assert engine.decide_state(overall=0.10, evidence_count=9) == "observation"


def test_observation_service_accumulates_evidence_then_requires_human(tmp_path: Path):
    from information_system.observation import DomainObservationService, ObservationEngine
    from information_system.recognition import RecognitionEngine

    store = _store(tmp_path)
    recognizer = RecognitionEngine()
    service = DomainObservationService(store, ObservationEngine())

    report = recognizer.recognize(
        _object(13, title="飞盘组局", text=UNKNOWN_TEXT), UNKNOWN_TEXT, known_domains=KNOWN_DOMAINS
    )
    first = service.observe(report, UNKNOWN_TEXT, title="飞盘组局", object_id="INFO-1")
    assert first is not None
    assert first.state == "observation", first.reason
    assert len(first.object_ids) == 1

    second = service.observe(report, UNKNOWN_TEXT, title="飞盘组局", object_id="INFO-2")
    assert second.state == "candidate"
    assert second.object_ids == ("INFO-1", "INFO-2")
    assert sum(second.growth.values()) == 2

    suggestions = service.suggested_promotions(min_evidence=2)
    assert [item["label"] for item in suggestions] == ["飞盘组局"]
    assert suggestions[0]["action"] == "await_human_confirmation"

    domain = service.promote_topic("飞盘组局", actor="agent")
    assert domain.state == "candidate"
    assert store.get_domain("飞盘组局")["state"] == "candidate"

    with pytest.raises(ValueError, match="requires an actor"):
        service.promote_topic("飞盘组局", actor="  ")
    with pytest.raises(ValueError, match="domain already exists"):
        service.promote_topic("飞盘组局", actor="agent")

    with pytest.raises(ValueError, match="requires a human actor"):
        service.confirm_domain("飞盘组局", actor="")
    assert service.confirm_domain("飞盘组局", actor="蓝") == "confirmed"
    assert store.get_domain("飞盘组局")["confirmed_by"] == "蓝"


def test_observation_service_ignores_objects_that_have_a_home(tmp_path: Path):
    from information_system.observation import DomainObservationService
    from information_system.recognition import RecognitionEngine

    store = _store(tmp_path)
    text = "考研 408 的复习方法：先过教材建立框架，再刷真题定位薄弱点。"
    obj = _object(14, title="408 复习方法", text=text)
    report = RecognitionEngine().recognize(obj, text, known_domains=KNOWN_DOMAINS)
    service = DomainObservationService(store)
    assert service.observe(report, text, title="408 复习方法", object_id="INFO-3") is None
    assert store.list_topics() == []


def test_topic_state_machine_blocks_skipping_candidate(tmp_path: Path):
    from information_system.models import LayerVerdict, TopicObservation

    store = _store(tmp_path)
    store.upsert_topic(
        TopicObservation(
            label="待观察",
            state="observation",
            layers=(LayerVerdict(layer="semantic_distance", score=0.9, reason="无邻接领域"),),
            confidence=0.9,
            reason="仅出现一次",
        )
    )
    with pytest.raises(ValueError, match="illegal topic transition"):
        store.transition_topic("待观察", "confirmed")
    assert store.transition_topic("待观察", "candidate") == "candidate"
    assert store.get_topic("待观察")["state"] == "candidate"


def test_unknown_backlog_lists_single_occurrence_items(tmp_path: Path):
    from information_system.observation import DomainObservationService
    from information_system.recognition import RecognitionEngine

    store = _store(tmp_path)
    text = "今天下午在楼下咖啡店坐了会儿，天有点阴。"
    obj = _object(15, title="随手记", text=text)
    report = RecognitionEngine().recognize(obj, text, known_domains=KNOWN_DOMAINS)
    DomainObservationService(store).observe(report, text, title="随手记", object_id="INFO-4")
    backlog = DomainObservationService(store).unknown_backlog()
    assert len(backlog) == 1
    assert backlog[0]["state"] == "observation"
    assert backlog[0]["evidence_count"] == 1
    assert backlog[0]["label"] == "随手记"


# -------------------------------------------------------------- 初始领域种子


def test_initial_domains_come_from_schema_not_code():
    from information_system.observation import DOMAIN_REGISTRY_SCHEMA, load_initial_domains

    names = load_initial_domains()
    payload = json.loads(DOMAIN_REGISTRY_SCHEMA.read_text(encoding="utf-8"))
    assert names == tuple(payload["initial_domains"])
    assert names  # 非空


def test_seed_initial_domains_is_idempotent_and_confirmed(tmp_path: Path):
    from information_system.observation import resolve_known_domains, seed_initial_domains

    store = _store(tmp_path)
    first = seed_initial_domains(store)
    second = seed_initial_domains(store)
    assert first == second
    assert len(store.list_domains()) == len(first)
    assert all(row["state"] == "confirmed" for row in store.list_domains())
    # 注册表按 name 排序返回，集合等价即可（识别时领域顺序不影响打分）
    assert set(resolve_known_domains(store)) == set(first)
    assert set(resolve_known_domains(store, seed_if_empty=False)) == set(first)


def test_resolve_known_domains_can_skip_seeding(tmp_path: Path):
    from information_system.observation import resolve_known_domains

    store = _store(tmp_path)
    assert resolve_known_domains(store, seed_if_empty=False) == ()
    assert store.list_domains() == []


# ------------------------------------------------------------ Inbox 接线


def test_ingestion_pipeline_stores_object_report_and_lifecycle(tmp_path: Path):
    from information_system.inbox import IngestionPipeline

    store = _store(tmp_path)
    pipeline = IngestionPipeline(store)
    text = "考研 408 的复习方法：先过教材建立框架，再刷真题定位薄弱点。"
    outcome = pipeline.ingest(source="ima", title="408 复习方法", content=text, source_ref="m-1")

    assert outcome.created is True
    assert outcome.domains == ("学习",)
    assert outcome.recommendation == "needs_human_review"

    row = store.get(outcome.object_id)
    assert row["status"] == "inbox"
    assert row["domains"] == ["学习"]
    assert row["excerpt"] and len(row["excerpt"]) <= 200
    assert row["knowledge_level"] == "knowledge_candidate"
    assert row["cognitive_os_level"].endswith("_candidate")
    assert [item["event_type"] for item in store.history(outcome.object_id)] == [
        "captured",
        "lifecycle",
        "updated",
    ]
    assert store.latest_report(outcome.object_id)["recognition"]["object_id"] == outcome.object_id


def test_ingestion_pipeline_is_idempotent_by_source_ref(tmp_path: Path):
    from information_system.inbox import IngestionPipeline

    store = _store(tmp_path)
    pipeline = IngestionPipeline(store)
    first = pipeline.ingest(source="ima", title="同一条", content="正文", source_ref="m-42")
    second = pipeline.ingest(source="ima", title="同一条", content="正文", source_ref="m-42")
    assert first.object_id == second.object_id
    assert first.created is True and second.created is False
    assert store.count() == 1


def test_ingestion_pipeline_never_assigns_a_domain_to_unknown_topics(tmp_path: Path):
    from information_system.inbox import IngestionPipeline

    store = _store(tmp_path)
    pipeline = IngestionPipeline(store)
    text = "这个飞盘组局的步骤是：先定场地，再约人，最后定规则。我实测下来，先定规则比先约人省事得多。"
    outcome = pipeline.ingest(source="manual", title="飞盘组局", content=text)
    assert outcome.domains == ()
    assert outcome.topic_label == "飞盘组局"
    row = store.get(outcome.object_id)
    assert row["domains"] == []
    assert row["unknown_topic"] is True
    assert row["domain_candidates"] == []


def test_ingestion_pipeline_rejects_bad_input(tmp_path: Path):
    from information_system.inbox import IngestError, IngestionPipeline

    pipeline = IngestionPipeline(_store(tmp_path))
    with pytest.raises(IngestError, match="unsupported source"):
        pipeline.ingest(source="telepathy", title="t", content="c")
    with pytest.raises(IngestError, match="title is required"):
        pipeline.ingest(source="manual", title=" ", content="c")
    with pytest.raises(IngestError, match="content is required"):
        pipeline.ingest(source="manual", title="t", content="  ")


def test_capture_adapter_writer_persists_into_information_store(tmp_path: Path):
    from information_system.inbox import IngestionPipeline
    from integrations.capture import CaptureAdapter

    store = _store(tmp_path)
    pipeline = IngestionPipeline(store)
    adapter = CaptureAdapter(writer=pipeline.as_capture_writer())
    item = adapter.capture(
        source="ima",
        title="条目",
        content="这是一段用于落库的正文内容。",
        correlation_id="corr-1",
        source_ref="m-7",
        source_container="kb-1",
    )
    assert item["destination"] == "00_Inbox"
    assert store.count() == 1
    row = next(iter(store.list_objects()))
    assert row["source_ref"] == "m-7"
    assert row["source_container"] == "kb-1"
    assert row["correlation_id"] == "corr-1"


# --------------------------------------------------- IMA → Inbox 编排


def _fake_ima_adapter(items: list[dict]) -> object:
    from integrations.ima import DEFAULT_ENDPOINTS, ImaAdapter

    path = DEFAULT_ENDPOINTS["get_knowledge_list"]

    class _Transport:
        def __call__(self, request_path: str, payload: dict) -> dict:
            assert request_path == path
            return {"knowledge_list": items, "next_cursor": "", "is_end": True}

    return ImaAdapter(transport=_Transport(), network_mode="ASSIST")


def test_sync_ima_to_inbox_ingests_parsed_and_reports_the_rest(tmp_path: Path):
    from agents.information_pipeline import sync_ima_to_inbox
    from information_system.inbox import IngestionPipeline

    store = _store(tmp_path)
    pipeline = IngestionPipeline(store)
    adapter = _fake_ima_adapter(
        [
            {"media_id": "m-1", "title": "已解析一", "introduction": "考研 408 复习方法", "media_state": 2},
            {"media_id": "m-2", "title": "解析中", "introduction": "还在解析", "media_state": 1},
            {"media_id": "m-3", "title": "已解析二", "introduction": "AI 协作原则", "media_state": 2},
        ]
    )
    summary = sync_ima_to_inbox(adapter=adapter, knowledge_base_id="kb-1", pipeline=pipeline)
    assert summary.scanned == 3
    assert summary.ingested == 2
    assert summary.skipped_unparsed == 1
    assert summary.skipped_titles == ("解析中",)
    assert summary.duplicates == 0

    again = sync_ima_to_inbox(adapter=adapter, knowledge_base_id="kb-1", pipeline=pipeline)
    assert again.ingested == 0
    assert again.duplicates == 2
    assert store.count() == 2
    assert [item["source"] for item in store.list_objects()] == ["ima", "ima"]


def test_sync_ima_to_inbox_can_include_unparsed(tmp_path: Path):
    from agents.information_pipeline import sync_ima_to_inbox
    from information_system.inbox import IngestionPipeline

    store = _store(tmp_path)
    adapter = _fake_ima_adapter(
        [{"media_id": "m-9", "title": "解析中", "introduction": "内容", "media_state": 1}]
    )
    summary = sync_ima_to_inbox(
        adapter=adapter,
        knowledge_base_id="kb-1",
        pipeline=IngestionPipeline(store),
        only_parsed=False,
    )
    assert summary.ingested == 1
    assert summary.skipped_unparsed == 0


def test_information_pipeline_pending_review_is_read_only(tmp_path: Path):
    from agents.information_pipeline import InformationPipeline

    store = _store(tmp_path)
    pipeline = InformationPipeline(store)
    pipeline.ingest(source="manual", title="原则", content="和 AI 协作有一条铁律：永远先把上下文喂全。")
    before = store.count()
    pending = pipeline.pending_review()
    assert store.count() == before
    assert any(item["kind"] == "object_review" for item in pending)


# --------------------------------------------------------------- 回归守卫


def test_information_system_does_not_import_business_layers():
    """信息层必须保持单向依赖：不得反向依赖执行引擎 / agents / knowledge_system。"""
    package = PROJECT_ROOT / "information_system"
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("from agents", "import agents", "from runtime_core", "from knowledge_system"):
            if forbidden in text:
                offenders.append(f"{path.name}: {forbidden}")
    assert offenders == []



# ------------------------------------------------- 主题路径（taxonomy，方案 b）


def _seeded_store(tmp_path: Path):
    from information_system.observation import resolve_known_domains

    store = _store(tmp_path)
    resolve_known_domains(store)
    return store


def test_taxonomy_reads_domains_from_registry_not_code_constants(tmp_path: Path):
    """领域清单只能来自注册表：代码里不得出现硬编码的领域名清单。"""
    source = (PROJECT_ROOT / "information_system" / "taxonomy.py").read_text(encoding="utf-8")
    for name in KNOWN_DOMAINS:
        assert f'"{name}"' not in source, f"taxonomy.py 不应硬编码领域名 {name}"

    from information_system.taxonomy import confirmed_domain_names

    names = confirmed_domain_names(_seeded_store(tmp_path))
    assert set(names) == set(KNOWN_DOMAINS)


def test_taxonomy_unknown_topic_falls_back_to_unclassified_without_guessing(tmp_path: Path):
    """invariant：「无法自然容纳时必须先落 unknown，不得强行归入现有领域」。"""
    from information_system.taxonomy import UNCLASSIFIED_SEGMENT, decide_segments, is_unclassified

    store = _seeded_store(tmp_path)
    domains = store.list_domains()
    for blank in (None, "", "   "):
        segments = decide_segments(domains=domains, domain_name=blank)
        assert segments == (UNCLASSIFIED_SEGMENT,)
        assert is_unclassified(segments)


def test_taxonomy_rejects_unconfirmed_and_unknown_domains_loudly(tmp_path: Path):
    """candidate/observation 不得参与自动分类；未知领域不得静默降级。"""
    from information_system.models import DomainRecord
    from information_system.taxonomy import ThemePathError, decide_segments

    store = _seeded_store(tmp_path)
    store.upsert_domain(DomainRecord(name="待观察领域", state="observation", reason="测试"))
    store.upsert_domain(
        DomainRecord(name="候选领域", state="candidate", reason="测试", evidence=("x",), confidence=0.5)
    )
    domains = store.list_domains()

    assert decide_segments(domains=domains, domain_name="AI") == ("AI",)
    with pytest.raises(ThemePathError, match="只有 'confirmed' 可参与自动分类"):
        decide_segments(domains=domains, domain_name="候选领域")
    with pytest.raises(ThemePathError, match="只有 'confirmed' 可参与自动分类"):
        decide_segments(domains=domains, domain_name="待观察领域")
    with pytest.raises(ThemePathError, match="不在 DomainRegistry 中"):
        decide_segments(domains=domains, domain_name="压根不存在的领域")


def test_taxonomy_path_is_ancestor_chain_and_grows_without_code_change(tmp_path: Path):
    """路径 = 领域祖先链。长出子领域后路径自动变两级，无需改代码。"""
    from information_system.models import DomainRecord, make_domain_id
    from information_system.taxonomy import decide_segments, format_path

    store = _seeded_store(tmp_path)
    life = store.get_domain("生活")
    assert life is not None
    store.upsert_domain(
        DomainRecord(
            name="财务",
            state="confirmed",
            parent_id=str(life["domain_id"]),
            confirmed_by="tester",
            reason="测试：在「生活」下长出「财务」",
        )
    )
    assert make_domain_id("财务") == store.get_domain("财务")["domain_id"]

    domains = store.list_domains()
    assert decide_segments(domains=domains, domain_name="AI") == ("AI",)
    child = decide_segments(domains=domains, domain_name="财务")
    assert child == ("生活", "财务")
    assert format_path(child) == "生活/财务"


def test_taxonomy_rejects_unconfirmed_ancestor_and_broken_chain(tmp_path: Path):
    """祖先链含未确认领域、或父 id 悬空、或成环时，一律拒绝而不是给个残缺路径。"""
    from information_system.models import DomainRecord
    from information_system.taxonomy import ThemePathError, decide_segments

    store = _seeded_store(tmp_path)
    ai = store.get_domain("AI")
    store.upsert_domain(
        DomainRecord(name="提示词", state="confirmed", parent_id="DOM-不存在的父", confirmed_by="t", reason="测试悬空父")
    )
    store.upsert_domain(DomainRecord(name="未确认父", state="candidate", reason="测试", evidence=("x",), confidence=0.5))
    unconfirmed_parent_id = str(store.get_domain("未确认父")["domain_id"])
    store.upsert_domain(
        DomainRecord(name="子领域", state="confirmed", parent_id=unconfirmed_parent_id, confirmed_by="t", reason="测试")
    )

    domains = store.list_domains()
    with pytest.raises(ThemePathError, match="在注册表中不存在"):
        decide_segments(domains=domains, domain_name="提示词")
    with pytest.raises(ThemePathError, match="祖先链含未确认领域"):
        decide_segments(domains=domains, domain_name="子领域")

    # 自环：父指向自己
    store.upsert_domain(DomainRecord(name="环形领域", state="confirmed", confirmed_by="t", reason="测试"))
    ring_id = str(store.get_domain("环形领域")["domain_id"])
    store.upsert_domain(
        DomainRecord(name="环形领域", state="confirmed", parent_id=ring_id, confirmed_by="t", reason="测试自环")
    )
    with pytest.raises(ThemePathError, match="存在环"):
        decide_segments(domains=store.list_domains(), domain_name="环形领域")
    assert ai is not None


MOUNTED_NOTE_ID = "7505497510904002"
NOTE_MOUNTED_MEDIA_ID = "note_033209398da9751a42b6c3220e604491_75054975109040027505484386931481"


class FakeWikiTree:
    """**带状态**的 IMA 知识库假体。

    为什么必须有状态：`create_folder` 建出来的文件夹要能被后续的列举查到，
    否则「第二次挂载复用了同一路径」根本测不出来（固定响应的 FakeTransport 做不到）。
    """

    def __init__(self, *, seed: dict[str, list[dict]] | None = None) -> None:
        self.tree: dict[str, list[dict]] = {k: list(v) for k, v in (seed or {}).items()}
        self.calls: list[tuple[str, dict]] = []
        self._seq = 0

    def __call__(self, path: str, payload: dict) -> dict:
        from integrations.ima import DEFAULT_ENDPOINTS

        self.calls.append((path, payload))
        if path == DEFAULT_ENDPOINTS["get_knowledge_list"]:
            parent = str(payload.get("folder_id") or "")
            return {"knowledge_list": list(self.tree.get(parent, [])), "is_end": True}
        if path == DEFAULT_ENDPOINTS["create_folder"]:
            self._seq += 1
            media_id = f"folder_new_{self._seq}"
            parent = str(payload.get("folder_id") or "")
            self.tree.setdefault(parent, []).append(
                {"media_id": media_id, "title": payload["name"], "media_type": 99}
            )
            return {"media_id": media_id}
        if path == DEFAULT_ENDPOINTS["add_knowledge"]:
            self._seq += 1
            note_id = payload["note_info"]["content_id"]
            media_id = f"note_hash_{note_id}{self._seq}"
            parent = str(payload.get("folder_id") or "")
            self.tree.setdefault(parent, []).append(
                {"media_id": media_id, "title": payload["title"], "media_type": 11}
            )
            return {"media_id": media_id}
        return {}

    def payloads(self, key: str) -> list[dict]:
        from integrations.ima import DEFAULT_ENDPOINTS

        path = DEFAULT_ENDPOINTS[key]
        return [payload for called, payload in self.calls if called == path]


def _tree_adapter(fake: FakeWikiTree):
    from integrations.ima import ImaAdapter

    return ImaAdapter(transport=fake, network_mode="ASSIST")


def test_taxonomy_chain_rejects_blank_and_separator_names():
    """路径段不得含 `/`；`domain_chain` 拒绝空白名（`decide_segments` 则走未分类，不抛）。"""
    from information_system.taxonomy import (
        UNCLASSIFIED_SEGMENT,
        DomainIndex,
        ThemePathError,
        decide_segments,
        domain_chain,
    )

    domains = [{"name": "含/斜杠", "domain_id": "DOM-x", "state": "confirmed", "parent_id": None}]
    with pytest.raises(ThemePathError, match="不得含"):
        decide_segments(domains=domains, domain_name="含/斜杠")

    index = DomainIndex.build(domains)
    with pytest.raises(ThemePathError, match="领域名不能为空"):
        domain_chain(index, "   ")
    with pytest.raises(ThemePathError, match="领域名不能为空"):
        domain_chain(index, "")

    # 空白领域名在 decide_segments 里是「未知主题」语义 → 落未分类，而不是报错
    assert decide_segments(domains=domains, domain_name="   ") == (UNCLASSIFIED_SEGMENT,)


def test_ima_ensure_folder_path_reuses_existing_folders_without_creating():
    """幂等：同名文件夹已存在时必须复用，一次都不该创建。"""
    fake = FakeWikiTree(
        seed={
            "": [{"media_id": "folder_root_ai", "title": "AI", "media_type": 99},
                 {"media_id": "m-1", "title": "一篇文档", "media_type": 7}],
            "folder_root_ai": [{"media_id": "folder_ai_child", "title": "提示词", "media_type": 99}],
        }
    )
    adapter = _tree_adapter(fake)
    deep = adapter.ensure_folder_path(knowledge_base_id="kb-1", segments=["AI", "提示词"])
    assert deep == "folder_ai_child"
    assert fake.payloads("create_folder") == [], "路径已存在，不该创建任何文件夹"

    # 非文件夹条目不得被误认为目标（「一篇文档」不能匹配）
    assert adapter.ensure_folder_path(knowledge_base_id="kb-1", segments=["一篇文档"]) == "folder_new_1"

    # 空路径 → 落根目录，不需要 folder_id，也不该再去列举
    fake.calls.clear()
    assert adapter.ensure_folder_path(knowledge_base_id="kb-1", segments=[]) == ""
    assert fake.calls == []


def test_ima_ensure_folder_path_creates_only_missing_levels():
    """缺失的层级才创建，且父目录字段必须用 `folder_id`。"""
    fake = FakeWikiTree(seed={"": [{"media_id": "folder_seed_ai", "title": "AI", "media_type": 99}]})
    adapter = _tree_adapter(fake)
    result = adapter.ensure_folder_path(knowledge_base_id="kb-1", segments=["AI", "提示词"])
    assert result == "folder_new_1"

    creates = fake.payloads("create_folder")
    assert len(creates) == 1, "第一级已存在，只应创建第二级"
    assert creates[0] == {"knowledge_base_id": "kb-1", "name": "提示词", "folder_id": "folder_seed_ai"}
    assert "parent_folder_id" not in creates[0]

    with pytest.raises(ValueError, match="路径段不能为空"):
        adapter.ensure_folder_path(knowledge_base_id="kb-1", segments=["AI", "  "])


def test_note_mount_token_matches_media_id_layout():
    """挂载返回的 media_id 末段以 note_id 开头 —— 这是去重判据。"""
    from agents.note_taxonomy import MIN_NOTE_ID_LENGTH, note_mount_token

    real = "note_033209398da9751a42b6c3220e604491_75054975109040027505484386931481"
    assert note_mount_token("7505497510904002", real)
    assert not note_mount_token("9999999999999999", real)
    assert not note_mount_token("", real)
    assert not note_mount_token("7505497510904002", "")

    # 短 id 一律判为「未挂载」：短 id 下 startswith 会假阳性，
    # 而假阳性 = 误判为已挂载 → 漏挂丢数据，比重复挂载更糟。
    assert MIN_NOTE_ID_LENGTH == 12
    # 样例 id 长于下限，故可正常匹配；截到下限以下就必须被挡掉
    # （注意这个前缀确实是 media_id 末段的真前缀，否则该用例无法证明守卫生效）。
    short = "7505497510904002"[: MIN_NOTE_ID_LENGTH - 1]
    assert len(short) == MIN_NOTE_ID_LENGTH - 1
    assert real.rsplit("_", 1)[-1].startswith(short), "该前缀必须真的能 startswith，否则用例无效"
    assert not note_mount_token(short, real)
    assert not note_mount_token("1111", "note_hash_1111extra")


def test_mount_note_by_theme_puts_notes_of_same_domain_on_one_path(tmp_path: Path):
    """方案 (b)：同主题的多篇笔记挂到**同一路径**，且路径只建一次。"""
    from agents.note_taxonomy import mount_notes_by_theme

    fake = FakeWikiTree()
    adapter = _tree_adapter(fake)
    store = _seeded_store(tmp_path)

    results = mount_notes_by_theme(
        adapter=adapter,
        store=store,
        knowledge_base_id="kb-1",
        notes=[
            {"note_id": "7505497510904001", "title": "提示词心得", "domain_name": "AI"},
            {"note_id": "7505497510904002", "title": "上下文管理", "domain_name": "AI"},
            {"note_id": "7505497510904003", "title": "无主题笔记", "domain_name": None},
        ],
    )
    assert [item.path for item in results] == ["AI", "AI", "未分类"]
    assert all(item.mounted for item in results)
    assert [item.unclassified for item in results] == [False, False, True]

    creates = fake.payloads("create_folder")
    assert len(creates) == 2, f"AI 与 未分类 各建一次，不能重复建：{creates}"
    assert [payload["name"] for payload in creates] == ["AI", "未分类"]

    adds = fake.payloads("add_knowledge")
    assert len(adds) == 3
    assert all(payload["media_type"] == 11 for payload in adds)
    assert [payload["note_info"]["content_id"] for payload in adds] == [
        "7505497510904001",
        "7505497510904002",
        "7505497510904003",
    ]
    assert adds[0]["folder_id"] == adds[1]["folder_id"], "同主题必须落在同一 folder_id"

    # run 级缓存生效：3 篇笔记只列举 4 次目录
    # （AI 解析 1 次 + AI 查重 1 次 + 未分类解析 1 次 + 未分类查重 1 次）。
    # 没有缓存的话，第 2 篇会再解析一次路径、再拉一次目录索引。
    assert len(fake.payloads("get_knowledge_list")) == 4, (
        f"run 缓存没生效：{len(fake.payloads('get_knowledge_list'))} 次目录列举"
    )


def test_mount_note_by_theme_skips_already_mounted_note(tmp_path: Path):
    """同一篇笔记重复挂载 → 跳过，不产生重复条目。"""
    from agents.note_taxonomy import mount_note_by_theme

    fake = FakeWikiTree(
        seed={
            "": [{"media_id": "folder_seed_ai", "title": "AI", "media_type": 99}],
            "folder_seed_ai": [
                {"media_id": NOTE_MOUNTED_MEDIA_ID, "title": "提示词心得", "media_type": 11}
            ],
        }
    )
    adapter = _tree_adapter(fake)
    store = _seeded_store(tmp_path)

    result = mount_note_by_theme(
        adapter=adapter,
        store=store,
        knowledge_base_id="kb-1",
        note_id=MOUNTED_NOTE_ID,
        title="提示词心得",
        domain_name="AI",
    )
    assert result.mounted is False
    assert result.path == "AI"
    assert "已存在" in result.skipped_reason
    assert fake.payloads("add_knowledge") == [], "已挂载过就不该再挂"
    assert fake.payloads("create_folder") == [], "路径已存在也不该再建"


def test_mount_note_by_theme_does_not_confuse_two_different_notes(tmp_path: Path):
    """同目录下已有**别的**笔记时，不能把新笔记误判为已挂载（否则会漏挂丢数据）。"""
    from agents.note_taxonomy import mount_note_by_theme

    fake = FakeWikiTree(
        seed={
            "": [{"media_id": "folder_seed_ai", "title": "AI", "media_type": 99}],
            "folder_seed_ai": [
                {"media_id": NOTE_MOUNTED_MEDIA_ID, "title": "已有笔记", "media_type": 11}
            ],
        }
    )
    adapter = _tree_adapter(fake)
    store = _seeded_store(tmp_path)
    result = mount_note_by_theme(
        adapter=adapter,
        store=store,
        knowledge_base_id="kb-1",
        note_id="7505499999999999",
        title="另一篇笔记",
        domain_name="AI",
    )
    assert result.mounted is True
    assert len(fake.payloads("add_knowledge")) == 1


def test_mount_note_by_theme_mounts_twice_when_dedupe_disabled(tmp_path: Path):
    """关掉去重时行为可预期：确实会挂第二遍（说明去重不是靠运气，而是靠判据）。"""
    from agents.note_taxonomy import mount_note_by_theme

    fake = FakeWikiTree(seed={"": [{"media_id": "folder_seed_ai", "title": "AI", "media_type": 99}]})
    adapter = _tree_adapter(fake)
    store = _seeded_store(tmp_path)
    result = mount_note_by_theme(
        adapter=adapter,
        store=store,
        knowledge_base_id="kb-1",
        note_id=MOUNTED_NOTE_ID,
        title="提示词心得",
        domain_name="AI",
        skip_if_already_mounted=False,
    )
    assert result.mounted is True
    assert len(fake.payloads("add_knowledge")) == 1

def test_suggest_domain_returns_none_instead_of_best_guess(tmp_path: Path):
    """推断不出领域时必须返回 None（落未分类），不得返回最接近的那个。"""
    from agents.note_taxonomy import suggest_domain

    store = _seeded_store(tmp_path)
    assert suggest_domain(store, title="提示词技巧", text="和大模型对话要先把上下文喂全") == "AI"
    assert suggest_domain(store, title="飞盘组局", text=UNKNOWN_TEXT) is None


def test_note_taxonomy_module_is_explicit_not_wired_into_pipeline():
    """挂载会写外部系统，必须显式调用，不得被 InformationPipeline 隐式触发。"""
    pipeline_src = (PROJECT_ROOT / "agents" / "information_pipeline.py").read_text(encoding="utf-8")
    assert "note_taxonomy" not in pipeline_src
    assert "mount_note" not in pipeline_src
