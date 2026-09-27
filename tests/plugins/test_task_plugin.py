from __future__ import annotations

import ast
from datetime import datetime
import importlib
import importlib.util
from pathlib import Path

import pytest

from capability_plugins import ActivationState, PluginRegistry, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "capability_plugins" / "manifests" / "task.yaml"
MANIFEST_DIR = MANIFEST_PATH.parent
EXPECTED_CAPABILITIES = (
    "task.parse",
    "task.list",
    "task.create_proposal",
    "task.update_proposal",
    "task.prioritize",
)


def _api():
    try:
        spec = importlib.util.find_spec("capability_plugins.task.plugin")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "capability_plugins.task.plugin is required"
    module = importlib.import_module("capability_plugins.task.plugin")
    return module.TaskPlugin, module.TaskPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "task"
    )


def test_task_manifest_and_adapter_share_ready_conservative_metadata():
    TaskPlugin, _ = _api()
    manifest = _manifest()

    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.reads
    assert manifest.writes == ()
    assert {"read_task", "propose_task_change"} <= set(manifest.permissions)
    assert manifest.risk_level.value == "medium"
    assert manifest.activation_mode == "always"
    assert manifest.enabled is True
    assert manifest.activation_state is ActivationState.ACTIVE
    assert TaskPlugin().manifest == manifest


def test_task_parse_matches_legacy_parser_and_record_core_fields():
    TaskPlugin, _ = _api()
    parser = importlib.import_module("02_执行引擎（Engine）.输入解析引擎.parser")
    builders = importlib.import_module("02_执行引擎（Engine）.输入解析引擎.builders")
    text = "#任务 提交周报 【项目：项目A】【截止：2026/09/30】【耗时：45分钟】"
    variables = parser.extract_variables(text)
    title = parser.extract_main_content(text)

    result = TaskPlugin().invoke("task.parse", {"text": text}, {})

    assert result["title"] == title
    assert result["variables"] == variables
    assert result["fields"] == builders.build_record(
        "执行库", title, variables, raw_text=text
    )
    assert result["lightweight"] is False


def test_lightweight_parse_reuses_legacy_handler_in_dry_run(monkeypatch):
    TaskPlugin, _ = _api()
    lightweight = importlib.import_module(
        "02_执行引擎（Engine）.输入解析引擎.handlers.lightweight"
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 26, 12, 0, 0)

    monkeypatch.setattr(lightweight, "datetime", FixedDateTime)
    text = "#临时 买牛奶 【项目：生活区】【截止：2026/09/30】"
    expected = lightweight.handle_lightweight_task(text, dry_run=True)

    result = TaskPlugin().invoke("task.parse", {"text": text}, {})

    assert result["lightweight"] is True
    assert result["title"] == "买牛奶"
    assert result["legacy_preview"] == expected
    assert expected["dry_run"] is True
    assert "不写执行库" in expected["message"]


def test_list_and_prioritize_use_injected_read_only_delegates():
    TaskPlugin, _ = _api()
    calls = []
    tasks = [{"task_guid": "t-2"}, {"task_guid": "t-1"}]

    def list_tasks(filters):
        calls.append(("list", filters))
        return [{"task_guid": "t-1", "status": filters["status"]}]

    def prioritize(items):
        calls.append(("prioritize", items))
        return sorted(items, key=lambda item: item["task_guid"])

    plugin = TaskPlugin(
        delegates={"task.list": list_tasks, "task.prioritize": prioritize}
    )
    listed = plugin.invoke("task.list", {"filters": {"status": "待处理"}}, {})
    ordered = plugin.invoke("task.prioritize", {"tasks": tasks}, {})

    assert listed == [{"task_guid": "t-1", "status": "待处理"}]
    assert [item["task_guid"] for item in ordered] == ["t-1", "t-2"]
    assert calls == [
        ("list", {"status": "待处理"}),
        ("prioritize", tasks),
    ]
    assert [item["task_guid"] for item in tasks] == ["t-2", "t-1"]


def test_delegate_result_is_detached_from_delegate_owned_state():
    TaskPlugin, _ = _api()
    cached = [{"task_guid": "t-1", "metadata": {"labels": ["source"]}}]
    plugin = TaskPlugin(delegates={"task.list": lambda filters: cached})

    result = plugin.invoke("task.list", {"filters": {}}, {})
    result[0]["metadata"]["labels"].append("caller-edit")

    assert cached == [{"task_guid": "t-1", "metadata": {"labels": ["source"]}}]


def test_task_create_proposal_reuses_project_execution_builder():
    TaskPlugin, _ = _api()
    builder = importlib.import_module("agents.project_execution").build_task_proposal
    payload = {
        "title": "准备周报",
        "evidence": ["meeting-1"],
        "project_id": "project-a",
        "assignee": "我自己",
        "due_at": "2026-09-30",
    }

    result = TaskPlugin().invoke("task.create_proposal", payload, {})

    assert result == builder(
        payload["title"],
        evidence=payload["evidence"],
        project_id=payload["project_id"],
        assignee=payload["assignee"],
        due_at=payload["due_at"],
    )
    assert result["status"] == "pending_human_review"
    assert result["executed"] is False
    assert result["requires_human_review"] is True


def test_task_update_proposal_is_data_only_and_requires_review():
    TaskPlugin, _ = _api()
    changes = {"status": "进行中", "priority": "P1-重要不紧急"}

    result = TaskPlugin().invoke(
        "task.update_proposal",
        {"task_guid": "task-123", "changes": changes},
        {},
    )

    assert result["proposal_type"] == "task_update"
    assert result["task_guid"] == "task-123"
    assert result["changes"] == changes
    assert result["approval"]["status"] == "pending_human_review"
    assert result["status"] == "pending_human_review"
    assert result["executed"] is False
    assert result["requires_human_review"] is True


def test_delegate_and_legacy_builder_failures_map_to_safe_errors():
    TaskPlugin, TaskPluginError = _api()

    def failing_list(_filters):
        raise RuntimeError("private source response")

    plugin = TaskPlugin(delegates={"task.list": failing_list})
    with pytest.raises(TaskPluginError) as list_error:
        plugin.invoke("task.list", {"filters": {}}, {})
    assert list_error.value.error_code == "task_list_failed"
    assert "private source response" not in str(list_error.value)
    assert list_error.value.__cause__ is None

    with pytest.raises(TaskPluginError) as proposal_error:
        TaskPlugin().invoke("task.create_proposal", {"title": "  "}, {})
    assert proposal_error.value.error_code == "invalid_input"
    assert proposal_error.value.__cause__ is None


def test_task_plugin_rejects_invalid_payload_and_unknown_capability():
    TaskPlugin, TaskPluginError = _api()
    plugin = TaskPlugin()

    with pytest.raises(TaskPluginError) as invalid:
        plugin.invoke("task.parse", {"text": "  "}, {})
    assert invalid.value.error_code == "invalid_input"

    with pytest.raises(TaskPluginError) as unknown:
        plugin.invoke("task.delete", {}, {})
    assert unknown.value.error_code == "unsupported_capability"


def test_plugin_has_no_direct_cli_or_network_imports():
    TaskPlugin, _ = _api()
    module = importlib.import_module("capability_plugins.task.plugin")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_roots = {"subprocess", "requests", "urllib", "socket", "httpx"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    plugin = TaskPlugin()
    proposal = plugin.invoke(
        "task.create_proposal", {"title": "不直接写入飞书"}, {}
    )
    assert imported_roots.isdisjoint(forbidden_roots)
    assert plugin.manifest.writes == ()
    assert proposal["executed"] is False


def test_disabling_plugin_does_not_change_legacy_lightweight_entrypoint(monkeypatch):
    TaskPlugin, _ = _api()
    lightweight = importlib.import_module(
        "02_执行引擎（Engine）.输入解析引擎.handlers.lightweight"
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 26, 12, 0, 0)

    monkeypatch.setattr(lightweight, "datetime", FixedDateTime)
    plugin = TaskPlugin()
    disabled_registry = PluginRegistry.from_manifests(
        [__import__("dataclasses").replace(plugin.manifest, enabled=False)]
    )
    text = "#临时 买牛奶"

    with pytest.raises(LookupError):
        disabled_registry.by_capability("task.parse")
    legacy_result = lightweight.handle_lightweight_task(text, dry_run=True)
    assert legacy_result["ok"] is True
    assert legacy_result["dry_run"] is True
    assert legacy_result["type"] == "lightweight"
    assert "买牛奶" in legacy_result["message"]
