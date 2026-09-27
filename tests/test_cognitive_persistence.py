"""Persistence Layer 测试：双写 / 部分失败 / 重试 / 幂等 / 冲突 / 双源检索去重。

对应计划书第三十八节 Dual Write / Partial Failure / Duplicate / Conflict / Retrieval，
以及第三十九节验收案例 Case 1-5。
"""

from __future__ import annotations

import pytest

from cognitive_system.ima_writer import ImaCognitiveWriter, extract_cognitive_id_from_title, render_markdown
from cognitive_system.feishu_writer import FeishuCognitiveWriter, build_record_fields
from cognitive_system.models import BilingualTag, CognitiveAsset
from cognitive_system.persistence import CognitivePersistenceLayer, PersistencePolicy
from cognitive_system.retrieval import CognitiveRetrieval
from cognitive_system.store import CognitiveStore


class FakeImaAdapter:
    """可注入故障的假 IMA 适配器。"""

    def __init__(self, *, fail_write=False, fail_append=False):
        self.fail_write = fail_write
        self.fail_append = fail_append
        self.notes: dict[str, str] = {}
        self.mounted: list[tuple[str, str, str]] = []
        self._counter = 0

    def create_note(self, content, *, title="", folder_id=""):
        if self.fail_write:
            raise RuntimeError("IMA 不可达")
        self._counter += 1
        note_id = f"doc_{self._counter:03d}"
        self.notes[note_id] = content
        return {"doc_id": note_id}

    def mount_note_into_knowledge(self, *, knowledge_base_id, note_id, title, folder_id=""):
        self.mounted.append((knowledge_base_id, note_id, title))
        return {}

    def append_note(self, note_id, content, *, content_format=1):
        if self.fail_append:
            raise RuntimeError("IMA 追加失败")
        self.notes[note_id] += content
        return {}

    def ensure_folder_path(self, *, knowledge_base_id, segments):
        return "folder_target"


class FakeFeishuClient:
    """可注入故障的假飞书 runner（模拟 lark-cli）。"""

    def __init__(self, *, fail=False):
        self.fail = fail
        self.records: dict[str, dict] = {}
        self._counter = 0

    def __call__(self, args, json_input=None):
        class R:
            def __init__(self, code, stdout, stderr=""):
                self.returncode = code
                self.stdout = stdout
                self.stderr = stderr

        if self.fail:
            return R(1, "", "lark-cli 失败")
        import json as jsonlib
        payload = jsonlib.loads(json_input) if json_input else {}
        if "+record-upsert" in args:
            self._counter += 1
            record_id = f"rec_{self._counter:03d}"
            self.records[record_id] = payload
            return R(0, jsonlib.dumps({"record": {"record_id": record_id}}))
        if "+record-batch-update" in args:
            for record_id in payload["record_id_list"]:
                self.records[record_id].update(payload["patch"])
            return R(0, jsonlib.dumps({}))
        return R(1, "", "未知命令")


def make_layer(store, ima, feishu_runner, *, policy=None):
    ima_writer = ImaCognitiveWriter(ima, knowledge_base_id="KB_TEST")
    feishu_writer = FeishuCognitiveWriter(
        base_token="BASE_TEST", table_id="TBL_TEST",
        runner=feishu_runner, network_mode="ASSIST",
    )
    return CognitivePersistenceLayer(
        store, writers={"ima": ima_writer, "feishu": feishu_writer}, policy=policy
    )


def sleep_asset(**overrides):
    base = dict(
        cognitive_type="experience",
        title="连续三天睡眠不足时训练表现下降",
        statement="三天睡眠不足后训练容量明显下降",
        tags=(BilingualTag(zh="睡眠", en="sleep"), BilingualTag(zh="训练", en="training")),
        confidence=0.8,
    )
    base.update(overrides)
    return CognitiveAsset(**base)


# ---------------------------------------------------------------- 双写成功

class TestDualWrite:
    def test_full_success_synced(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        ima = FakeImaAdapter()
        feishu = FakeFeishuClient()
        layer = make_layer(store, ima, feishu)
        outcome = layer.persist(sleep_asset())
        assert outcome.created
        assert outcome.sync_state == "SYNCED"
        assert all(result.status == "synced" for result in outcome.results)
        # IMA 标题携带 cognitive_id（去重锚点）
        assert ima.mounted and ima.mounted[0][2].startswith(f"[{outcome.cognitive_id}]")
        # 飞书记录包含双语标签字段
        record = list(feishu.records.values())[0]
        assert record["标签中文"] == ["睡眠", "训练"]
        assert record["标签英文"] == ["sleep", "training"]

    def test_policy_feishu_only(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        ima = FakeImaAdapter()
        feishu = FakeFeishuClient()
        layer = make_layer(store, ima, feishu, policy=PersistencePolicy(primary="feishu"))
        outcome = layer.persist(sleep_asset())
        assert outcome.sync_state == "FEISHU_ONLY"
        assert not ima.notes

    def test_policy_switch_preserves_assets(self, tmp_path):
        """策略切换不改业务代码（计划书第二十六节决策接口）。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        layer.set_policy(PersistencePolicy(primary="ima"))
        assert layer.policy.targets == ("ima",)


# ---------------------------------------------------------------- 部分失败 + 重试

class TestPartialFailure:
    def test_ima_success_feishu_failed(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        ima = FakeImaAdapter()
        feishu = FakeFeishuClient(fail=True)
        layer = make_layer(store, ima, feishu)
        outcome = layer.persist(sleep_asset())
        # 计划书第十节：不能因为一个库暂时失败，就认为整个认知资产不存在
        assert outcome.sync_state == "IMA_ONLY"
        asset = store.get_asset(outcome.cognitive_id)
        assert asset.cognitive_status == "active"
        assert asset.feishu_status == "failed"
        # 进入重试队列
        assert len(store.open_retries()) == 1

    def test_ima_failed_feishu_success_then_retry(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        ima = FakeImaAdapter(fail_write=True)
        feishu = FakeFeishuClient()
        layer = make_layer(store, ima, feishu)
        outcome = layer.persist(sleep_asset())
        assert outcome.sync_state == "FEISHU_ONLY"
        # 恢复 IMA 后重试成功
        ima.fail_write = False
        results = layer.retry_pending()
        assert results and results[0].sync_state == "SYNCED"
        assert store.open_retries() == []

    def test_no_writer_configured_marks_dead_not_infinite_retry(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = CognitivePersistenceLayer(store, writers={}, policy=PersistencePolicy())
        outcome = layer.persist(sleep_asset())
        assert outcome.sync_state == "PENDING"
        # writer 缺失不入重试队列（非瞬态故障）
        assert store.open_retries() == []
        assert [result.error for result in outcome.results] == ["writer 未配置", "writer 未配置"]


# ---------------------------------------------------------------- 幂等（Duplicate）

class TestDuplicate:
    def test_same_id_repeated_write_single_asset(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        first = layer.persist(sleep_asset())
        second = layer.persist(sleep_asset(cognitive_id=first.cognitive_id))
        assert second.created is False
        assert len(store.list_assets()) == 1

    def test_new_asset_gets_new_id(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        first = layer.persist(sleep_asset())
        second = layer.persist(sleep_asset(title="不同的经验"))
        assert first.cognitive_id != second.cognitive_id
        assert len(store.list_assets()) == 2


# ---------------------------------------------------------------- 冲突

class TestConflict:
    def test_remote_hash_mismatch_enters_conflict(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(sleep_asset())
        conflicted = layer.detect_remote_conflict(
            outcome.cognitive_id, target="ima", remote_hash="deadbeef"
        )
        assert conflicted
        asset = store.get_asset(outcome.cognitive_id)
        assert asset.ima_status == "conflict"
        assert asset.sync_state == "CONTENT_CONFLICT"
        # 内容本身不动（不自动覆盖，计划书第二十五节）
        assert asset.title == "连续三天睡眠不足时训练表现下降"

    def test_matching_hash_no_conflict(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(sleep_asset())
        asset = store.get_asset(outcome.cognitive_id)
        assert not layer.detect_remote_conflict(outcome.cognitive_id, target="feishu", remote_hash=asset.content_hash)
        assert store.get_asset(outcome.cognitive_id).sync_state == "SYNCED"


# ---------------------------------------------------------------- 更新

class TestUpdate:
    def test_update_bumps_version_ima_append_feishu_patch(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        ima = FakeImaAdapter()
        feishu = FakeFeishuClient()
        layer = make_layer(store, ima, feishu)
        outcome = layer.persist(sleep_asset())
        updated = layer.update_content(
            outcome.cognitive_id, statement="补充：恢复两天后表现回升", detail="追加观察"
        )
        assert updated.sync_state == "SYNCED"
        asset = store.get_asset(outcome.cognitive_id)
        assert asset.version == 2
        # IMA 是追加不是覆盖
        ima_content = ima.notes[asset.ima_ref]
        assert "补充：恢复两天后表现回升" in ima_content
        assert "三天睡眠不足后训练容量明显下降" in ima_content  # 旧内容仍在
        # 飞书是真更新
        record = feishu.records[asset.feishu_ref]
        assert record["版本"] == 2


# ---------------------------------------------------------------- IMA 渲染与去重锚点

class TestImaWriter:
    def test_render_markdown_bilingual_tags_and_meta(self, tmp_path):
        asset = sleep_asset(cognitive_id="EXP-20260915-000042")
        markdown = render_markdown(asset)
        assert "#睡眠 #sleep" in markdown
        assert "#训练 #training" in markdown
        assert "cognitive_id: EXP-20260915-000042" in markdown
        assert "经验 / Experience" in markdown

    def test_extract_cognitive_id_from_title(self):
        assert extract_cognitive_id_from_title("[KNW-20260915-000123] 标题") == "KNW-20260915-000123"
        assert extract_cognitive_id_from_title("无前缀标题") == ""

    def test_delete_is_platform_boundary(self, tmp_path):
        writer = ImaCognitiveWriter(FakeImaAdapter(), knowledge_base_id="KB")
        with pytest.raises(NotImplementedError, match="平台边界"):
            writer.delete("KNW-20260915-000001")


# ---------------------------------------------------------------- 飞书字段

class TestFeishuWriter:
    def test_off_mode_rejected(self):
        with pytest.raises(Exception, match="OFF"):
            FeishuCognitiveWriter(base_token="B", table_id="T", network_mode="OFF")

    def test_missing_config_rejected(self):
        with pytest.raises(Exception, match="base_token"):
            FeishuCognitiveWriter(base_token="", table_id="", network_mode="ASSIST")

    def test_build_record_fields_bilingual(self):
        fields = build_record_fields(sleep_asset(cognitive_id="EXP-20260915-000007"))
        assert fields["类型"] == "经验 Experience"
        assert fields["标签中文"] == ["睡眠", "训练"]
        assert fields["标签英文"] == ["sleep", "training"]
        assert fields["认知ID"] == "EXP-20260915-000007"


# ---------------------------------------------------------------- 双源检索去重

class TestRetrieval:
    def test_dedup_by_cognitive_id_single_object_returned(self, tmp_path):
        """计划书第三十四节：同一认知资产存在两库，检索只返回 1 个对象。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(sleep_asset())

        def ima_searcher(query):
            return [{"title": f"[{outcome.cognitive_id}] 连续三天睡眠不足", "media_id": "m1"}]

        def feishu_searcher(query):
            return [{"fields": {"认知ID": outcome.cognitive_id, "标题": "连续三天睡眠不足"}}]

        retrieval = CognitiveRetrieval(store, ima_searcher=ima_searcher, feishu_searcher=feishu_searcher)
        hits = retrieval.search("睡眠")
        assert len(hits) == 1
        assert hits[0].cognitive_id == outcome.cognitive_id
        assert set(hits[0].sources) == {"local", "ima", "feishu"}
        assert hits[0].asset is not None

    def test_unanchored_ima_items_not_merged(self, tmp_path):
        """无 cognitive_id 前缀的 IMA 条目不参与去重合并（避免假阳性撞库）。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        retrieval = CognitiveRetrieval(
            store, ima_searcher=lambda query: [{"title": "普通文章", "media_id": "m2"}]
        )
        assert retrieval.search("普通文章") == []

    def test_searcher_failure_degrades_gracefully(self, tmp_path):
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(sleep_asset())

        def broken_searcher(query):
            raise RuntimeError("网络不可达")

        retrieval = CognitiveRetrieval(store, ima_searcher=broken_searcher)
        hits = retrieval.search("睡眠")
        assert len(hits) == 1 and hits[0].cognitive_id == outcome.cognitive_id


# ---------------------------------------------------------------- 验收案例（计划书第三十九节）

class TestAcceptanceCases:
    def _mapping(self):
        from tests.test_cognitive_system import FakeInfoObject
        from cognitive_system.mapping import extract_cognitive_assets
        return extract_cognitive_assets

    def test_case2_experience_associates_bilingual_tags(self, tmp_path):
        """Case 2: 「我连续三天睡眠不足，今天训练明显下降」→ Experience，双库同步。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(sleep_asset())
        assert outcome.sync_state == "SYNCED"
        asset = store.get_asset(outcome.cognitive_id)
        assert asset.cognitive_type == "experience"

    def test_case4_belief(self, tmp_path):
        """Case 4: 「我觉得以后应该优先保证恢复」→ Belief。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        outcome = layer.persist(
            sleep_asset(
                cognitive_type="belief",
                title="优先保证恢复，而不是一味增加训练量",
            )
        )
        asset = store.get_asset(outcome.cognitive_id)
        assert asset.cognitive_type == "belief"
        assert asset.sync_state == "SYNCED"

    def test_case5_decision_links_insight_and_belief(self, tmp_path):
        """Case 5: 「接下来四周我决定降低训练量」→ Decision，关联 Insight/Belief。"""
        store = CognitiveStore(tmp_path / "db.sqlite")
        layer = make_layer(store, FakeImaAdapter(), FakeFeishuClient())
        belief = layer.persist(sleep_asset(
            cognitive_type="belief", title="优先保证恢复",
        ))
        decision = layer.persist(sleep_asset(
            cognitive_type="decision",
            title="未来四周降低训练量",
            relations=(),
        ))
        from cognitive_system.models import Relation
        linked = sleep_asset(
            cognitive_type="decision",
            title="未来四周降低训练量",
            cognitive_id=decision.cognitive_id,
            relations=(Relation(relation_type="based_on", target_cognitive_id=belief.cognitive_id),),
        )
        layer.persist(linked)
        asset = store.get_asset(decision.cognitive_id)
        assert asset.relations[0].target_cognitive_id == belief.cognitive_id
        assert len(store.list_assets(cognitive_type="decision")) == 1
