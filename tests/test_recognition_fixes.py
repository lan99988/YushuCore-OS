"""验收问题修复的回归测试（P1 全部 + P2 两项）。

对应文档：`07_系统文档（Docs）/2026-09-16_验收问题修复方案.md`

纪律：本文件**只断言行为**，不修改被测代码；所有时间相关用例注入固定 `moment`。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from information_system.inbox import IngestionPipeline
from information_system.models import DomainRecord, InformationObject, content_digest
from information_system.observation import DomainObservationService
from information_system.projects import ProjectRecord, ProjectResolver
from information_system.recognition import RecognitionEngine
from information_system.store import InformationStore

KNOWN_DOMAINS = ("工作", "学习", "生活", "阅读", "AI")
NOW = datetime(2026, 9, 16, 9, 0, 0)  # 2026-09-16 星期三


def _store(tmp_path: Path) -> InformationStore:
    store = InformationStore(tmp_path / "fixes.db")
    store.init_schema()
    return store


def _resolver() -> ProjectResolver:
    return ProjectResolver(
        projects=(
            ProjectRecord(name="个人混合管理系统", aliases=("混合管理系统", "Personal AI OS")),
            ProjectRecord(name="考研408", aliases=("408",)),
        )
    )


def _engine() -> RecognitionEngine:
    return RecognitionEngine(projects=_resolver())


def _report(text: str, *, title: str = "标题", moment: datetime | None = NOW):
    obj = InformationObject(
        source="manual", title=title, source_ref="fix", content_digest=content_digest(text)
    )
    return _engine().recognize(obj, text, known_domains=KNOWN_DOMAINS, moment=moment)


def _pipeline(store: InformationStore) -> IngestionPipeline:
    return IngestionPipeline(
        store, recognizer=_engine(), known_domains=KNOWN_DOMAINS
    )


# ------------------------------------------------------------------ P1-1 时间词表

@pytest.mark.parametrize(
    "text",
    [
        "下周之前需要完成项目 A 的数据库迁移。",
        "下下周把材料交齐。",
        "下个月启动新阶段。",
        "明年再复盘这件事。",
    ],
)
def test_p1_1_relative_time_words_are_recognised(text: str):
    report = _report(text)
    assert report.temporal.label in {"short_term", "long_term"}
    assert report.temporal.confidence > 0


# ------------------------------------------------------- P1-6 deadline 抽取

def test_p1_6_pipeline_persists_deadline_from_relative_expression(tmp_path: Path):
    store = _store(tmp_path)
    outcome = _pipeline(store).ingest(
        source="manual", title="报价", content="明天上午 10 点给客户发送报价。", moment=NOW
    )
    row = store.get(outcome.object_id)
    assert row["temporal"] == "short_term"
    assert row["deadline"] is not None
    assert datetime.fromisoformat(row["deadline"]).replace(tzinfo=None) == datetime(2026, 9, 17, 10, 0)
    assert row["attributes"]["temporal"]["kind"] == "point"


def test_p1_6_window_time_is_kept_as_window_not_deadline(tmp_path: Path):
    store = _store(tmp_path)
    outcome = _pipeline(store).ingest(
        source="manual", title="迁移", content="下周之前需要完成项目 A 的数据库迁移。", moment=NOW
    )
    row = store.get(outcome.object_id)
    assert row["temporal"] == "short_term"
    assert row["deadline"] is None, "时间窗口不得被伪装成精确 deadline"
    detail = row["attributes"]["temporal"]
    assert detail["kind"] == "window"
    assert detail["window_start"] and detail["window_end"]


# ------------------------------------------------- P1-2 / P1-3 认知 OS 判定

def test_p1_2_normative_sentence_becomes_os_candidate():
    report = _report("以后所有重要项目开始之前，都应该先明确目标、边界、输入、输出和成功标准。")
    assert report.cognitive_os_level.endswith("_candidate")
    assert report.cognitive_os_detected is True


def test_p1_2_plain_future_task_is_not_an_os_candidate():
    """反例保护：裸 `以后` 不得触发 OS（否则普通任务被误判为方法论）。"""
    report = _report("以后每天写周报。")
    assert report.cognitive_os_level == "none"


def test_p1_3_descriptive_sentence_is_not_an_os_candidate():
    report = _report("Transformer 是一种基于注意力机制的神经网络架构。")
    assert report.cognitive_os_level == "none"
    assert report.knowledge_level == "knowledge_candidate"


def test_p1_3_method_keyword_still_triggers_os_candidate():
    """反例保护：方法类表述仍是 OS 候选（现有基线行为不得被收窄误伤）。"""
    report = _report("考研 408 的复习方法：先过教材建立框架，再刷真题定位薄弱点。")
    assert report.cognitive_os_level.endswith("_candidate")


# ------------------------------------------------------------ P1-4 / P1-5 类型

@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("Transformer 是一种基于注意力机制的神经网络架构。", "model"),
        ("以后所有项目都应该建立报价模板。", "method"),
        ("做任何决策前都要守住底线。", "principle"),
    ],
)
def test_p1_4_type_vocabulary_covers_architecture_and_template(text: str, expected_type: str):
    report = _report(text)
    assert expected_type in report.types


def test_p1_5_template_sentence_is_knowledge_not_task():
    report = _report("以后所有项目都应该建立报价模板。")
    assert "task" not in report.types
    assert report.knowledge_level == "knowledge_candidate"


# --------------------------------------------------------------- P1-7 行动识别

def test_p1_7_imperative_sentence_produces_action_candidate():
    report = _report("明天上午 10 点给客户发送报价。")
    assert report.actions, "祈使句行动线索被漏检"


@pytest.mark.parametrize(
    "text",
    ["我今天整理了桌面。", "上午已经把材料提交给客户了。"],
)
def test_p1_7_past_tense_is_not_an_action(text: str):
    report = _report(text)
    assert not report.actions, "已发生的事不应被当作待办"


def test_p1_7_capability_statement_is_not_an_action():
    report = _report("AI Agent 可以帮助个人自动整理财务记录，并根据历史消费习惯给出预算建议。")
    assert not report.actions, "能力陈述（可以/能够）不应被当作待办"


def test_p1_7_explicit_marker_still_wins_over_past_tense_gate():
    report = _report("需要重新整理这份笔记。")
    assert report.actions


# ------------------------------------------------------------- P1-8 项目匹配

def test_p1_8_registered_project_name_is_matched():
    report = _report("个人混合管理系统下周需要完成数据库迁移。")
    assert [item.label for item in report.projects] == ["个人混合管理系统"]
    hit = report.projects[0]
    assert hit.confidence > 0 and hit.evidence and hit.reason


def test_p1_8_alias_is_resolved_to_canonical_name():
    report = _report("混合管理系统这周要把信息层收尾。")
    assert [item.label for item in report.projects] == ["个人混合管理系统"]


def test_p1_8_unregistered_placeholder_is_not_invented():
    report = _report("项目 A 下周需要完成数据库迁移。")
    assert report.projects == (), "未登记的项目名不得被猜出来"


def test_p1_8_shipped_config_is_loadable_and_non_empty():
    resolver = ProjectResolver.from_config()
    assert not resolver.is_empty
    assert "考研408" in {record.name for record in resolver.projects}


def test_p1_8_missing_config_yields_empty_resolver(tmp_path: Path):
    resolver = ProjectResolver.from_config(tmp_path / "nope.yaml")
    assert resolver.is_empty
    assert resolver.resolve(title="x", text="随便什么内容") == ()


# ------------------------------------------------------ 治理不变式不得被削弱

def test_projects_and_deadline_do_not_relax_unknown_topic_verdict(tmp_path: Path):
    """接了项目/时间数据源后，未知主题仍须进观察区（不得被强行归类）。"""
    store = _store(tmp_path)
    text = "个人混合管理系统下周要处理量子退相干噪声的谱密度建模。"
    outcome = _pipeline(store).ingest(source="manual", title="未知主题", content=text, moment=NOW)
    row = store.get(outcome.object_id)
    assert row["unknown_topic"] is True
    assert row["domains"] == []


def test_recognition_still_never_emits_formal_knowledge_level():
    report = _report("《运动神经元》这本书给了一条原则：绝不可以跳过基础。")
    assert report.knowledge_level in {"information", "knowledge_candidate"}


# --------------------------------------------------- P2 同内容不同来源提示

def test_p2_same_content_from_two_sources_records_duplicate_hint(tmp_path: Path):
    store = _store(tmp_path)
    pipeline = _pipeline(store)
    text = "AI Agent 通过规划任务与调用工具，帮助个人处理重复性工作。"
    first = pipeline.ingest(source="web", title="来源A", content=text, source_ref="src-A")
    second = pipeline.ingest(source="web", title="来源B", content=text, source_ref="src-B")

    assert first.created and second.created
    assert first.object_id != second.object_id, "不同来源各自保留独立对象"
    assert second.duplicate_of == first.object_id

    events = [item["event_type"] for item in store.history(second.object_id)]
    assert "duplicate_candidate" in events
    assert store.get(first.object_id) is not None, "不得因重复而删除原始来源"


def test_p2_same_source_ref_stays_idempotent_without_duplicate_event(tmp_path: Path):
    store = _store(tmp_path)
    pipeline = _pipeline(store)
    text = "同一来源重复推送。"
    first = pipeline.ingest(source="web", title="A", content=text, source_ref="same")
    again = pipeline.ingest(source="web", title="A", content=text, source_ref="same")
    assert again.created is False
    assert again.duplicate_of == ""
    events = [item["event_type"] for item in store.history(again.object_id)]
    assert "duplicate_candidate" not in events
    assert store.count() == 1


def test_p2_find_by_content_digest_excludes_self(tmp_path: Path):
    store = _store(tmp_path)
    pipeline = _pipeline(store)
    text = "指纹查询测试正文。"
    outcome = pipeline.ingest(source="manual", title="A", content=text)
    digest = store.get(outcome.object_id)["content_digest"]
    assert store.find_by_content_digest(digest, exclude_object_id=outcome.object_id) == []
    assert len(store.find_by_content_digest(digest)) == 1


# ------------------------------------------------------ P2 领域合并建议（只读）

def _seed(store: InformationStore, *names: str) -> None:
    for name in names:
        store.upsert_domain(DomainRecord(name=name, state="candidate", reason="测试种子"))


def test_p2_merge_suggestions_detects_plural_forms_without_merging(tmp_path: Path):
    store = _store(tmp_path)
    _seed(store, "AI Agent", "AI Agents")
    service = DomainObservationService(store)

    suggestions = service.merge_suggestions()
    pair = {(item["left"], item["right"]) for item in suggestions}
    assert ("AI Agent", "AI Agents") in pair
    hit = next(item for item in suggestions if item["right"] == "AI Agents")
    assert hit["action"] == "await_human_confirmation"
    assert hit["similarity"] >= 0.8

    # 只读：两个领域都还在，状态未被改动，也没有产生新领域
    assert store.get_domain("AI Agent")["state"] == "candidate"
    assert store.get_domain("AI Agents")["state"] == "candidate"
    assert len(store.list_domains()) == 2


def test_p2_merge_suggestions_are_empty_for_distinct_names(tmp_path: Path):
    store = _store(tmp_path)
    _seed(store, "工作", "学习", "生活")
    assert DomainObservationService(store).merge_suggestions() == []


def test_p2_merge_suggestions_do_not_guess_pure_synonyms(tmp_path: Path):
    """纯语义同义（智能代理 / Agent）宁可漏报也不错并——需模型或人工判断。"""
    store = _store(tmp_path)
    _seed(store, "智能代理", "Agent")
    assert DomainObservationService(store).merge_suggestions() == []
