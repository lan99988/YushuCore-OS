"""认知资产层测试：模型 / ID / 标签 / 映射 / 本地库。

对应计划书第三十八节 Basic 与 Multi-object 部分。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cognitive_system.ids import CognitiveIdAllocator, format_cognitive_id
from cognitive_system.mapping import extract_cognitive_assets
from cognitive_system.models import (
    BilingualTag,
    CognitiveAsset,
    Relation,
    content_hash_of,
)
from cognitive_system.store import CognitiveStore, compute_sync_state
from cognitive_system.tags import TagRegistry


# ---------------------------------------------------------------- 模型

class TestModels:
    def test_bilingual_tag_requires_en_when_confirmed(self):
        with pytest.raises(ValueError, match="英文"):
            BilingualTag(zh="睡眠", en="")

    def test_bilingual_tag_candidate_allows_missing_en(self):
        tag = BilingualTag(zh="新标签", en="", status="candidate")
        assert tag.is_candidate

    def test_asset_type_prefix_validation(self):
        asset = CognitiveAsset(cognitive_type="knowledge", title="t", cognitive_id="KNW-20260915-000001")
        assert asset.type_prefix == "KNW"
        with pytest.raises(ValueError, match="前缀"):
            CognitiveAsset(cognitive_type="knowledge", title="t", cognitive_id="EXP-20260915-000001")

    def test_cognitive_status_and_persistence_status_separated(self):
        asset = CognitiveAsset(
            cognitive_type="experience", title="t",
            cognitive_status="active", ima_status="synced", feishu_status="failed",
        )
        # 认知状态不随持久化状态变化（计划书第十一节）
        assert asset.cognitive_status == "active"
        assert asset.ima_status == "synced"
        assert asset.feishu_status == "failed"

    def test_content_hash_stable_and_sensitive(self):
        base = dict(title="t", statement="s", tags=(BilingualTag(zh="睡眠", en="sleep"),), version=1)
        assert content_hash_of(**base) == content_hash_of(**base)
        assert content_hash_of(**base) != content_hash_of(**{**base, "statement": "s2"})
        assert content_hash_of(**base) != content_hash_of(**{**base, "version": 2})

    def test_bump_version_resets_persistence(self):
        asset = CognitiveAsset(
            cognitive_type="belief", title="旧", statement="旧",
            cognitive_id="BEL-20260915-000001",
            ima_status="synced", feishu_status="synced", sync_state="SYNCED",
        )
        bumped = asset.bump_version(statement="新", title="新")
        assert bumped.version == 2
        assert bumped.ima_status == "pending" and bumped.feishu_status == "pending"
        assert bumped.sync_state == "PENDING"
        # 认知状态不变
        assert bumped.cognitive_status == "active"


# ---------------------------------------------------------------- ID

class TestIds:
    def test_format_and_allocate(self):
        allocator = CognitiveIdAllocator(now=lambda: datetime(2026, 9, 15))
        first = allocator.allocate("knowledge")
        second = allocator.allocate("knowledge")
        third = allocator.allocate("insight")
        assert first == "KNW-20260915-000001"
        assert second == "KNW-20260915-000002"
        assert third == "INS-20260915-000001"

    def test_invalid_type_rejected(self):
        allocator = CognitiveIdAllocator()
        with pytest.raises(ValueError):
            allocator.allocate("widget")


# ---------------------------------------------------------------- 标签

class TestTags:
    def test_seed_lookup_bilingual(self):
        registry = TagRegistry()
        tag = registry.lookup("睡眠")
        assert tag == BilingualTag(zh="睡眠", en="sleep", status="confirmed")

    def test_unknown_tag_becomes_candidate_and_recorded(self):
        recorded = []
        registry = TagRegistry(saver=lambda zh, en, status: recorded.append((zh, en, status)))
        tag = registry.lookup("存在主义")
        assert tag.is_candidate
        registry.record_candidate("存在主义")
        assert recorded == [("存在主义", "", "candidate")]

    def test_register_requires_en(self):
        registry = TagRegistry()
        with pytest.raises(ValueError):
            registry.register("新域", "")
        tag = registry.register("新域", "new-domain")
        assert tag.status == "confirmed"

    def test_normalize_dedup_and_bilingual(self):
        registry = TagRegistry()
        tags = registry.normalize(("睡眠", "睡眠", "训练"))
        assert len(tags) == 2
        assert all(tag.en for tag in tags)

    def test_reverse_lookup(self):
        registry = TagRegistry()
        assert registry.reverse("sleep").zh == "睡眠"
        assert registry.reverse("nonexistent") is None


# ---------------------------------------------------------------- 映射（Multi-object）

class FakeInfoObject:
    """最小鸭子类型，模拟 information_system.InformationObject。"""

    def __init__(self, **kwargs):
        defaults = dict(
            object_id="INFO-abc",
            title="睡眠不足影响训练表现",
            excerpt="连续三天睡眠不足时训练表现下降",
            types=(),
            domains=(),
            concepts=(),
            relations=(),
            cognitive_os_level="none",
            confidence=0.7,
        )
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


class ScoredStub:
    def __init__(self, label, confidence=0.6):
        self.label = label
        self.confidence = confidence


class TestMapping:
    def test_experience_plus_insight_multi_object(self):
        obj = FakeInfoObject(types=("experience",), cognitive_os_level="insight")
        assets = extract_cognitive_assets(obj)
        kinds = {asset.cognitive_type for asset in assets}
        assert kinds == {"experience", "insight"}
        # 计划书 Case 3：不能简单只存成 Note
        assert "note" not in kinds

    def test_fact_maps_to_knowledge(self):
        obj = FakeInfoObject(types=("fact",))
        assets = extract_cognitive_assets(obj)
        assert len(assets) == 1
        assert assets[0].cognitive_type == "knowledge"

    def test_opinion_belief_decision_note(self):
        obj = FakeInfoObject(types=("opinion", "decision", "idea"))
        kinds = {asset.cognitive_type for asset in extract_cognitive_assets(obj)}
        assert kinds == {"belief", "decision", "note"}

    def test_concepts_become_concept_assets(self):
        obj = FakeInfoObject(types=("fact",), concepts=(ScoredStub("恢复能力"), ScoredStub("训练容量")))
        assets = extract_cognitive_assets(obj)
        concept_titles = [asset.title for asset in assets if asset.cognitive_type == "concept"]
        assert concept_titles == ["恢复能力", "训练容量"]

    def test_os_rule_not_mapped(self):
        obj = FakeInfoObject(types=("os_rule", "fact"))
        kinds = {asset.cognitive_type for asset in extract_cognitive_assets(obj)}
        assert kinds == {"knowledge"}

    def test_domains_become_bilingual_tags(self):
        obj = FakeInfoObject(types=("fact",), domains=("学习",))
        assets = extract_cognitive_assets(obj)
        assert assets[0].tags == (BilingualTag(zh="学习", en="learning"),)

    def test_relations_attached_to_first_asset(self):
        obj = FakeInfoObject(
            types=("experience",),
            relations=(ScoredStub("relates_to"), ),
        )
        # relations 鸭子类型：relation_type / target_object_id / confidence
        relation_stub = type("R", (), {"relation_type": "relates_to", "target_object_id": "INFO-xyz", "confidence": 0.5})()
        obj.relations = (relation_stub,)
        assets = extract_cognitive_assets(obj)
        assert assets[0].relations == (Relation(relation_type="relates_to", target_cognitive_id="INFO-xyz", confidence=0.5),)


# ---------------------------------------------------------------- 本地库

class TestStore:
    @pytest.fixture()
    def store(self, tmp_path):
        return CognitiveStore(tmp_path / "cognitive.db")

    def test_sequence_monotonic(self, store):
        assert store.next_sequence("KNW", "20260915") == 1
        store.save_asset(CognitiveAsset(
            cognitive_type="knowledge", title="t",
            cognitive_id=format_cognitive_id("KNW", "20260915", 1),
        ))
        assert store.next_sequence("KNW", "20260915") == 2
        assert store.next_sequence("KNW", "20260916") == 1

    def test_save_and_get_roundtrip(self, store):
        asset = CognitiveAsset(
            cognitive_type="decision",
            title="未来四周降低训练量",
            statement="基于恢复洞察",
            tags=(BilingualTag(zh="训练", en="training"),),
            relations=(Relation(relation_type="based_on", target_cognitive_id="INS-20260915-000001"),),
            cognitive_id="DEC-20260915-000001",
            confidence=0.8,
        )
        store.save_asset(asset)
        loaded = store.get_asset("DEC-20260915-000001")
        # created_at/updated_at 由 store 落库时注入，语义字段逐一比对
        assert loaded.title == asset.title
        assert loaded.statement == asset.statement
        assert loaded.tags == asset.tags
        assert loaded.relations == asset.relations
        assert loaded.confidence == asset.confidence
        assert loaded.cognitive_type == asset.cognitive_type
        assert loaded.created_at and loaded.updated_at

    def test_find_by_source_object(self, store):
        store.save_asset(CognitiveAsset(
            cognitive_type="experience", title="t", source_object_id="INFO-abc",
            cognitive_id="EXP-20260915-000001",
        ))
        assert len(store.find_by_source_object("INFO-abc")) == 1
        assert len(store.find_by_source_object("INFO-abc", cognitive_type="knowledge")) == 0

    def test_update_persistence_recomputes_sync_state(self, store):
        store.save_asset(CognitiveAsset(
            cognitive_type="knowledge", title="t", cognitive_id="KNW-20260915-000001",
        ))
        store.update_persistence("KNW-20260915-000001", target="ima", status="synced", ref="note_1")
        asset = store.get_asset("KNW-20260915-000001")
        assert asset.ima_status == "synced"
        assert asset.sync_state == "IMA_ONLY"
        store.update_persistence("KNW-20260915-000001", target="feishu", status="synced", ref="rec_1")
        asset = store.get_asset("KNW-20260915-000001")
        assert asset.sync_state == "SYNCED"

    def test_update_persistence_rejects_bad_target(self, store):
        store.save_asset(CognitiveAsset(cognitive_type="knowledge", title="t", cognitive_id="KNW-20260915-000002"))
        with pytest.raises(ValueError):
            store.update_persistence("KNW-20260915-000002", target="notion", status="synced")

    def test_retry_queue_upsert_counts_attempts(self, store):
        store.save_asset(CognitiveAsset(cognitive_type="knowledge", title="t", cognitive_id="KNW-20260915-000003"))
        store.enqueue_retry("KNW-20260915-000003", "feishu", "timeout")
        store.enqueue_retry("KNW-20260915-000003", "feishu", "timeout again")
        entries = store.open_retries()
        assert len(entries) == 1
        assert entries[0]["attempts"] == 2
        store.mark_retry("KNW-20260915-000003", "feishu", status="done")
        assert store.open_retries() == []

    def test_tag_registry_roundtrip_and_candidates(self, store):
        store.upsert_tag("训练", "training", "confirmed")
        store.upsert_tag("新词", "", "candidate")
        assert store.load_tags() == {"训练": "training"}
        candidates = store.list_tag_candidates()
        assert [item["zh"] for item in candidates] == ["新词"]

    def test_compute_sync_state_matrix(self):
        assert compute_sync_state("synced", "synced", local_hash="h", ima_hash="h", feishu_hash="h") == "SYNCED"
        assert compute_sync_state("synced", "synced", local_hash="h", ima_hash="h", feishu_hash="OTHER") == "CONTENT_CONFLICT"
        assert compute_sync_state("synced", "pending") == "IMA_ONLY"
        assert compute_sync_state("pending", "synced") == "FEISHU_ONLY"
        assert compute_sync_state("failed", "pending") == "SYNC_FAILED"
        assert compute_sync_state("pending", "failed") == "SYNC_FAILED"
        assert compute_sync_state("pending", "pending") == "PENDING"
        assert compute_sync_state("conflict", "synced") == "CONTENT_CONFLICT"

    def test_search_assets(self, store):
        store.save_asset(CognitiveAsset(
            cognitive_type="knowledge", title="睡眠与认知表现",
            statement="睡眠不足影响高认知负荷任务",
            cognitive_id="KNW-20260915-000004",
            tags=(BilingualTag(zh="睡眠", en="sleep"),),
        ))
        assert len(store.search_assets("睡眠")) == 1
        assert store.search_assets("不存在") == []
