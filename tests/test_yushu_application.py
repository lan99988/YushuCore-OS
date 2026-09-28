from __future__ import annotations

from pathlib import Path

from yushu_app.application import YushuApplication
from yushu_app.profile import Profile


def _app(tmp_path: Path) -> YushuApplication:
    return YushuApplication(Profile.initialize("test", home=tmp_path))


def test_capability_is_governed_and_persists_across_restart(tmp_path: Path):
    app = _app(tmp_path)
    created = app.invoke_capability(
        "local_record.create", {"kind": "task", "data": {"title": "写周报"}},
        agent_id="agent-a", correlation_id="corr-create",
    )
    assert created["status"] == "completed"
    assert created["schema_version"] == 1
    assert created["data"]["record"]["data"]["title"] == "写周报"

    reopened = YushuApplication(Profile.open("test", home=tmp_path))
    listed = reopened.invoke_capability(
        "local_record.list", {"kind": "task"}, agent_id="agent-b", correlation_id="corr-list"
    )
    assert listed["status"] == "completed"
    assert len(listed["data"]["records"]) == 1
    assert listed["source"] == "local"


def test_all_capabilities_are_discoverable_but_missing_executors_are_unavailable(tmp_path: Path):
    app = _app(tmp_path)
    catalog = app.capabilities()
    names = {entry["name"] for entry in catalog}
    assert {"local_record.create", "knowledge.search", "task.list"} <= names
    assert next(entry for entry in catalog if entry["name"] == "task.list")["status"] == "unavailable"
    knowledge = next(entry for entry in catalog if entry["name"] == "knowledge.search")
    assert knowledge["status"] == "unavailable"
    assert knowledge["reason_code"] == "not_configured"
    assert next(entry for entry in catalog if entry["name"] == "knowledge.health")["status"] == "ready"

    result = app.invoke_capability("task.list", {}, agent_id="agent-a", correlation_id="corr-missing")
    assert result["status"] == "unavailable"
    assert result["error_code"] == "plugin_executor_missing"
    missing_ima = app.invoke_capability("knowledge.list", {}, agent_id="agent-a")
    assert missing_ima["error_code"] == "not_configured"
    assert missing_ima["source"] == "ima"
    assert missing_ima["stale"] is True


def test_six_local_flows_have_stable_results(tmp_path: Path):
    app = _app(tmp_path)
    capture = app.run_flow("capture", "买牛奶", context={"kind": "task"}, agent_id="owner")
    assert capture["status"] == "completed"
    plan = app.run_flow("plan", "提高英语能力", agent_id="owner")
    assert plan["status"] == "completed"
    today = app.run_flow("today", "今天做什么", agent_id="owner")
    assert today["status"] == "completed"
    assert len(today["data"]["tasks"]) == 1
    adjust = app.run_flow("adjust", "调整任务", agent_id="owner")
    assert adjust["status"] == "needs_clarification"
    review = app.run_flow("review", "复盘", agent_id="owner")
    assert review["data"]["counts"]["task"] == 1
    explore = app.run_flow("explore", "英语", agent_id="owner")
    assert explore["status"] == "partial"
    assert explore["data"]["local_matches"]
    assert explore["data"]["knowledge_status"] == "not_configured"


def test_capture_imports_staged_text_file_without_accessing_other_paths(tmp_path: Path):
    app = _app(tmp_path)
    imports = app.profile.root / "imports"
    imports.mkdir()
    (imports / "idea.md").write_text("项目灵感", encoding="utf-8")

    result = app.run_flow("capture", "导入文件", context={"file": "idea.md"}, agent_id="owner")
    assert result["status"] == "completed"
    assert result["data"]["record"]["data"]["content"] == "项目灵感"
    denied = app.run_flow("capture", "导入文件", context={"file": "../../secret.md"}, agent_id="owner")
    assert denied["status"] == "blocked"


def test_manifest_contract_rejects_invalid_local_write_before_execution(tmp_path: Path):
    app = _app(tmp_path)
    rejected = app.invoke_capability("local_record.create", {"kind": "task", "data": "not an object"},
                                     agent_id="owner", correlation_id="corr-invalid")
    assert rejected["status"] == "blocked"
    assert rejected["error_code"] == "invalid_payload"
    assert app.store.list("task") == []


def test_review_does_not_silently_ignore_feishu_authority(tmp_path: Path):
    profile = Profile.initialize("feishu", home=tmp_path, authorities={"task": "feishu"})
    app = YushuApplication(profile)
    review = app.run_flow("review", "复盘", agent_id="owner")
    assert review["status"] == "partial"
    assert "task" in review["data"]["unavailable_sources"]
