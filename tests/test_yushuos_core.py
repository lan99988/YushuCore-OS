import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest
import yaml

from yushuos.config import load_config
from yushuos.deployment import activate_release, deploy, install_host, install_plugin, lock_plugin, rollback, uninstall_host, verify_release
from yushuos import __version__
from yushuos.models import ExecutionPlan, PlanStep, Request
from yushuos.runtime import CoreRuntime
from yushuos_sdk import Result
from yushuos_sdk.state import StateStore


ROOT = Path(__file__).resolve().parents[1]


def make_plugin(config_root: Path, *, write: bool = False, permissions=None) -> Path:
    plugin = config_root / "plugins" / "example.echo"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "templates" / "plugin-template", plugin)
    if write:
        manifest_path = plugin / "plugin.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["permissions"] = list(permissions or [])
        capability = manifest["capabilities"][0]
        capability["effect"] = "external_write"
        capability["intents"] = ["write"]
        capability["permissions"] = list(permissions or [])
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)
    return plugin


def write_config(config_root: Path, config: dict) -> None:
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def copy_release_source(target: Path) -> Path:
    target.mkdir()
    for name in ("yushuos", "yushuos_sdk", "templates"):
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def test_manifest_route_executes_portable_plugin_and_reduces_environment(tmp_path, monkeypatch):
    config_root = tmp_path / "core"
    plugin = make_plugin(config_root)
    runner = plugin / "run.py"
    source = runner.read_text(encoding="utf-8")
    source = source.replace("import json\n", "import json\nimport os\n")
    source = source.replace('{"received": request.fields["message"]}',
                            '{"received": request.fields["message"], "secret_seen": "YUSHUOS_TEST_SECRET" in os.environ}')
    runner.write_text(source, encoding="utf-8")
    lock_plugin(plugin)
    monkeypatch.setenv("YUSHUOS_TEST_SECRET", "must-not-cross-the-plugin-boundary")

    runtime = CoreRuntime(config_root)
    route = runtime.parse("#example hello")
    assert route["status"] == "routed"
    assert route["plugin"] == "example.echo"
    result = runtime.invoke({
        "request_id": "route-read-1", "capability": "example.echo", "intent": "read",
        "fields": {"message": "hello"},
    })
    assert result.status == "succeeded"
    assert result.data == {"received": "hello", "secret_seen": False}
    missing = runtime.invoke({"request_id": "route-read-2", "capability": "example.echo", "intent": "read", "fields": {}})
    assert missing.status == "needs_clarification"


def test_project_configuration_cannot_expand_global_permissions(tmp_path):
    root = tmp_path / "core"
    write_config(root, {"permissions": {"grants": [], "denials": []}})
    project = tmp_path / "project.yaml"
    project.write_text("schema_version: 1\nproject_ref: test.project\npermissions:\n  grants: [example.echo]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不允许覆盖"):
        load_config(root, project_file=project)

    project.write_text("schema_version: 1\nproject_ref: test.project\nplugins:\n  versions: {example.echo: 0.1.0}\n", encoding="utf-8")
    config = load_config(root, project_file=project)
    assert config["project_ref"] == "test.project"
    assert config["permissions"]["grants"] == []
    runtime = CoreRuntime(root, project_file=project)
    request = {"request_id": "scope-1", "capability": "example.echo", "intent": "read"}
    with pytest.raises(ValueError, match="项目配置不匹配"):
        runtime._request(request)
    assert runtime._request({**request, "project_ref": "test.project"}).project_ref == "test.project"

    write_config(root, {"plugins": {"reject_missing_dependencies": False}})
    with pytest.raises(ValueError, match="插件发现"):
        load_config(root)


def test_empty_plugin_environment_still_supports_doctor_catalog_and_host_handoff(tmp_path):
    runtime = CoreRuntime(tmp_path / "empty-core")
    assert runtime.registry.catalog()["plugins"] == []
    assert runtime.parse("hello") == {
        "status": "handoff", "intent": "chat", "reason": "natural_language_is_host_owned",
        "route_basis": "host_natural_language",
    }
    doctor = runtime.doctor()
    assert doctor["plugin_count"] == 0
    assert doctor["manifest_errors"] == []


def test_host_disabled_plugin_cannot_be_reopened_by_project_plan_or_direct_call(tmp_path, monkeypatch):
    home = tmp_path / "home"
    settings = home / ".workbuddy" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"skillOverrides": {"example.echo": "off"}}), encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root = tmp_path / "core"
    make_plugin(root)
    project = tmp_path / "project.yaml"
    project.write_text(
        "schema_version: 1\nproject_ref: isolated.project\nplugins:\n  disabled: []\n  versions:\n    example.echo: 0.1.0\n",
        encoding="utf-8",
    )
    calls = []

    class Runner:
        def invoke(self, *args, **kwargs):
            calls.append(True)
            raise AssertionError("全局停用后不能执行插件")

    runtime = CoreRuntime(root, project_file=project, runner=Runner())
    route = runtime.parse("#example hello")
    assert route["status"] == "unavailable"
    assert "user_disabled" in route["reasons"]
    request = {"request_id": "disabled-direct-1", "capability": "example.echo", "intent": "read",
               "fields": {"message": "hello"}, "project_ref": "isolated.project"}
    assert runtime.invoke(request).status == "unavailable"
    plan = runtime.plan({"project_ref": "isolated.project", "steps": [{
        "step_id": "step-1", "request_id": "disabled-plan-1", "capability": "example.echo",
        "intent": "read", "fields": {"message": "hello"},
    }]})
    assert plan["steps"][0]["status"] == "unavailable"
    assert calls == []


def test_missing_dependency_cycle_and_incompatible_manifest_fail_closed(tmp_path):
    missing_root = tmp_path / "missing"
    missing = make_plugin(missing_root)
    path = missing / "plugin.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["dependencies"] = ["missing.runtime"]
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(missing)
    route = CoreRuntime(missing_root).parse("#example hello")
    assert route["status"] == "unavailable"
    assert "dependency_missing:missing.runtime" in route["reasons"]

    cycle_root = tmp_path / "cycle"
    first = make_plugin(cycle_root)
    first_manifest_path = first / "plugin.yaml"
    first_manifest = yaml.safe_load(first_manifest_path.read_text(encoding="utf-8"))
    first_manifest.update(id="example.one", name="One", dependencies=["example.two"])
    first_manifest["routes"][0]["prefix"] = "#one"
    first_manifest_path.write_text(yaml.safe_dump(first_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(first)
    second = cycle_root / "plugins" / "example.two"
    shutil.copytree(first, second, ignore=shutil.ignore_patterns("plugin.lock.json"))
    second_path = second / "plugin.yaml"
    second_manifest = yaml.safe_load(second_path.read_text(encoding="utf-8"))
    second_manifest.update(id="example.two", name="Two", dependencies=["example.one"])
    second_manifest["routes"][0]["prefix"] = "#two"
    second_path.write_text(yaml.safe_dump(second_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(second)
    catalog = CoreRuntime(cycle_root).registry.catalog()
    assert any("循环" in item["error"] for item in catalog["manifest_errors"])
    assert all(item["lifecycle_state"] == "blocked" for item in catalog["plugins"])

    invalid_root = tmp_path / "invalid"
    invalid = make_plugin(invalid_root)
    invalid_path = invalid / "plugin.yaml"
    invalid_manifest = yaml.safe_load(invalid_path.read_text(encoding="utf-8"))
    invalid_manifest["contract_version"] = 99
    invalid_path.write_text(yaml.safe_dump(invalid_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    errors = CoreRuntime(invalid_root).registry.catalog()["manifest_errors"]
    assert len(errors) == 1


def test_project_plugin_config_is_scoped_and_passed_to_selected_plugin(tmp_path):
    root = tmp_path / "core"
    plugin = make_plugin(root)
    runner = plugin / "run.py"
    source = runner.read_text(encoding="utf-8")
    source = source.replace('{"received": request.fields["message"]}',
                            '{"received": request.fields["message"], "project_policy": payload["plugin_config"]}')
    runner.write_text(source, encoding="utf-8")
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["configuration"] = {"type": "object", "additionalProperties": True}
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)
    write_config(root, {"plugins": {"config": {"example.echo": {"global_policy": "keep"}}}})
    project = tmp_path / "project.yaml"
    project.write_text(
        "schema_version: 1\nproject_ref: test.project\nplugins:\n  config:\n    example.echo:\n      data_contracts:\n        source_of_truth: feishu_base\n",
        encoding="utf-8",
    )
    request = {"request_id": "project-policy-1", "capability": "example.echo", "intent": "read",
               "fields": {"message": "hi"}, "project_ref": "test.project"}
    result = CoreRuntime(root, project_file=project).invoke(request)
    assert result.status == "succeeded"
    assert result.data["project_policy"] == {
        "global_policy": "keep", "data_contracts": {"source_of_truth": "feishu_base"},
    }


def test_plan_is_preview_only_and_creates_no_operation_or_workflow(tmp_path):
    root = tmp_path / "core"
    make_plugin(root, write=True, permissions=["calendar.write"])
    ledger = root / "operations.sqlite3"
    state = StateStore(ledger)
    state._prepare()
    write_config(root, {"state": {"ledger_path": str(ledger)},
                        "permissions": {"grants": ["calendar.write"], "denials": []}})
    runtime = CoreRuntime(root)
    assert runtime.state is not None and runtime.state.path.is_file()
    plan = runtime.plan({"steps": [{"step_id": "step-1", "request_id": "preview-only-1",
                                     "capability": "example.echo", "intent": "write",
                                     "fields": {"message": "would write"}}]})
    assert plan["status"] == "preview"
    assert plan["write_performed"] is False
    assert plan["steps"][0]["status"] == "ready", plan["steps"][0]["reasons"]
    assert plan["steps"][0]["expected_changes"] == {
        "effect": "external_write", "business_write_required": True,
        "target_fields": [], "resource_scopes": [],
    }
    assert state.receipt("preview-only-1") is None
    assert state.workflow(plan["plan_id"]) is None


def test_equal_length_prefixes_from_distinct_plugins_require_clarification(tmp_path):
    config_root = tmp_path / "core"
    first = make_plugin(config_root)
    second = config_root / "plugins" / "example.second"
    shutil.copytree(first, second, ignore=shutil.ignore_patterns("plugin.lock.json"))
    manifest_path = second / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["id"] = "example.second"
    manifest["name"] = "Second Example Plugin"
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(second)

    result = CoreRuntime(config_root).parse("#example hello")
    assert result["status"] == "needs_clarification"
    assert {candidate["plugin"] for candidate in result["candidates"]} == {"example.echo", "example.second"}


def test_plugin_versions_require_an_explicit_selection_when_multiple_are_installed(tmp_path):
    config_root = tmp_path / "core"
    version_root = config_root / "plugins" / "example.echo"
    version_root.mkdir(parents=True)
    for version in ("0.1.0", "0.2.0"):
        folder = version_root / version
        shutil.copytree(ROOT / "templates" / "plugin-template", folder)
        manifest_path = folder / "plugin.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
        lock_plugin(folder)

    runtime = CoreRuntime(config_root)
    route = runtime.parse("#example hi")
    assert route["status"] == "unavailable"
    assert "version_selection_required" in route["reasons"]

    write_config(config_root, {"plugins": {"versions": {"example.echo": "0.1.0"}}})
    selected = CoreRuntime(config_root).parse("#example hi")
    assert selected["status"] == "routed"
    assert selected["plugin"] == "example.echo"


def test_provider_ambiguity_and_missing_selection_are_explicit(tmp_path):
    root = tmp_path / "core"
    first = make_plugin(root)
    second = root / "plugins" / "example.second"
    shutil.copytree(first, second, ignore=shutil.ignore_patterns("plugin.lock.json"))
    path = second / "plugin.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["id"] = "example.second"
    manifest["routes"][0]["prefix"] = "#second"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(second)

    runtime = CoreRuntime(root)
    route = runtime.parse("#example hi")
    assert route["status"] == "unavailable"
    assert route["reasons"] == ["provider_selection_required"]
    catalog_entry = next(item for item in runtime.registry.catalog()["plugins"] if item["id"] == "example.echo")
    assert catalog_entry["capabilities"][0]["ambiguous_provider"] is True

    write_config(root, {"bindings": {"providers": {"example.echo": "missing.plugin"}}})
    route = CoreRuntime(root).parse("#example hi")
    assert route["status"] == "unavailable"
    assert route["reasons"] == ["selected_provider_missing"]


def test_route_alias_and_resource_scope_are_enforced_by_core(tmp_path):
    root = tmp_path / "core"
    plugin = make_plugin(root)
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"][0]["resource_scopes"] = {"workspace": "workspace_id"}
    manifest["routes"][0]["aliases"] = ["#echo"]
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)
    write_config(root, {"bindings": {"resources": {"workspace_id": "workspace-1"}}})

    runtime = CoreRuntime(root)
    routed = runtime.parse("#echo hello")
    assert routed["status"] == "routed"
    assert routed["prefix"] == "#echo"
    request = {"request_id": "scope-match", "capability": "example.echo", "intent": "read",
               "fields": {"message": "hi"}, "target": {"workspace": "workspace-1"}}
    assert runtime.invoke(request).status == "succeeded"
    mismatch = runtime.invoke({**request, "request_id": "scope-mismatch",
                               "target": {"workspace": "workspace-2"}})
    assert mismatch.status == "unavailable"
    assert mismatch.error["reason"] == "resource_scope_mismatch"

    write_config(root, {})
    assert CoreRuntime(root).parse("#example hi")["reasons"] == ["resource_scope_unbound:workspace_id"]


def test_generic_plugin_install_is_immutable_and_does_not_select_version(tmp_path):
    root = tmp_path / "core"
    source = tmp_path / "source-plugin"
    shutil.copytree(ROOT / "templates" / "plugin-template", source)
    lock_plugin(source)
    result = install_plugin(source, root)
    assert result["installed"] is True
    assert result["selected"] is False
    target = root / "plugins" / "example.echo" / "0.1.0"
    assert (target / "plugin.lock.json").is_file()
    assert install_plugin(source, root)["already_present"] is True

    (source / "run.py").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="锁定清单"):
        install_plugin(source, root)


def test_write_capability_requires_all_permissions_and_shared_ledger(tmp_path):
    config_root = tmp_path / "core"
    make_plugin(config_root, write=True, permissions=["calendar.write", "chat.send"])
    write_config(config_root, {"permissions": {"grants": ["calendar.write"], "denials": []}})
    called = []

    class Runner:
        def invoke(self, *args, **kwargs):
            called.append(True)
            raise AssertionError("门禁失败时不得调用插件")

    request = {"request_id": "write-check-1", "capability": "example.echo", "intent": "write",
               "fields": {"message": "hello"}}
    result = CoreRuntime(config_root, runner=Runner()).invoke(request, mode="execute", host_mode="execute")
    assert result.status == "unavailable"
    assert "permission_not_granted" in result.error["reasons"]
    assert called == []

    write_config(config_root, {"permissions": {"grants": ["calendar.write", "chat.send"], "denials": []}})
    result = CoreRuntime(config_root, runner=Runner()).invoke(request, mode="execute", host_mode="execute")
    assert result.status == "unavailable"
    assert "台账" in result.message
    assert called == []


def test_unknown_write_receipt_is_returned_without_replaying_plugin(tmp_path):
    config_root = tmp_path / "core"
    make_plugin(config_root, write=True, permissions=["calendar.write"])
    ledger = config_root / "operations.sqlite3"
    write_config(config_root, {
        "state": {"ledger_path": "operations.sqlite3"},
        "permissions": {"grants": ["calendar.write"], "denials": []},
    })
    request = Request("unknown-write-1", "example.echo", "write", {"message": "hello"})
    state = StateStore(ledger)
    assert state.claim(request)
    state.record(Result("unknown", request.request_id, "需要核对"))
    called = []

    class Runner:
        def invoke(self, *args, **kwargs):
            called.append(True)
            raise AssertionError("未知写入不得重放")

    runtime = CoreRuntime(config_root, runner=Runner())
    result = runtime.invoke(request.to_dict(), mode="execute", host_mode="execute")
    assert result.status == "unknown"
    assert called == []


def test_v01_operation_ledger_is_preserved_and_workflow_checkpoint_has_no_body(tmp_path):
    ledger = tmp_path / "operations.sqlite3"
    db = sqlite3.connect(ledger)
    db.executescript("""
        CREATE TABLE operations (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, resource_key TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT, updated TEXT NOT NULL);
        CREATE TABLE locks (resource_key TEXT PRIMARY KEY, request_id TEXT NOT NULL);
        CREATE TABLE events (calendar_id TEXT NOT NULL, event_id TEXT NOT NULL, task_guid TEXT, snapshot TEXT NOT NULL, PRIMARY KEY(calendar_id,event_id));
        PRAGMA user_version=1;
        INSERT INTO operations VALUES ('old-1','fingerprint','request:old-1','succeeded',NULL,'now');
    """)
    db.commit()
    db.close()

    state = StateStore(ledger)
    assert state.workflow("not-created") is None
    plan = ExecutionPlan.create("", [PlanStep("step-1", "example.echo", Request(
        "private-request-1", "example.echo", "read", {"message": "private-body-marker"}))])
    state.begin_plan(plan, {"step-1": ("example.echo", "0.1.0")})
    assert state.receipt("old-1")["status"] == "succeeded"
    assert b"private-body-marker" not in ledger.read_bytes()
    with sqlite3.connect(ledger) as check:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 1


def test_release_is_immutable_verified_and_rollback_changes_active_version(tmp_path):
    source = copy_release_source(tmp_path / "source")
    config_root = tmp_path / "private-core"
    first = deploy(source, config_root, "0.2.0")
    assert first["verified"]
    assert verify_release(config_root)["verified"]
    assert deploy(source, config_root, "0.2.0")["already_present"]
    launcher = config_root / "bin" / "yushuos.py"
    launched = subprocess.run([sys.executable, str(launcher), "doctor"], capture_output=True, text=True, timeout=20)
    assert launched.returncode == 0
    assert json.loads(launched.stdout)["core_version"] == __version__

    second = deploy(source, config_root, "0.2.1")
    assert second["verified"]
    assert json.loads((config_root / "active.json").read_text(encoding="utf-8"))["active"] == "0.2.1"
    assert rollback(config_root)["active"] == "0.2.0"

    (source / "yushuos" / "__init__.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="递增版本"):
        deploy(source, config_root, "0.2.0")

    release_file = config_root / "releases" / "0.2.0" / "yushuos" / "__init__.py"
    release_file.write_text("tampered", encoding="utf-8")
    assert verify_release(config_root)["verified"] is False
    rejected = subprocess.run([sys.executable, str(launcher), "doctor"], capture_output=True, text=True, timeout=20)
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["status"] == "failed"


def test_candidate_release_can_be_verified_before_activation(tmp_path):
    source = copy_release_source(tmp_path / "source")
    root = tmp_path / "yushuos-home"
    result = deploy(source, root, "0.2.0-rc1", activate=False)
    assert result["verified"] is True
    assert result["active"] is False
    assert verify_release(root, "0.2.0-rc1")["verified"] is True
    assert (root / "active.json").exists() is False

    activated = activate_release(root, "0.2.0-rc1")
    assert activated["active"] is True
    assert json.loads((root / "active.json").read_text(encoding="utf-8"))["active"] == "0.2.0-rc1"


def test_host_install_is_repeatable_and_refuses_user_edits(tmp_path):
    source = copy_release_source(tmp_path / "source")
    config_root = tmp_path / "private-core"
    deploy(source, config_root, "0.2.0")
    host_root = tmp_path / "host" / ".codex"
    assert install_host(config_root, host_root, host="codex")["installed"]
    target = host_root / "skills" / "yushuos-core" / "SKILL.md"
    assert "YushuOS Core" in target.read_text(encoding="utf-8")
    assert "legacy command prefixes" in target.read_text(encoding="utf-8")
    assert install_host(config_root, host_root, host="codex")["installed"]
    assert CoreRuntime(config_root).doctor()["host_installs"]["codex"] == "verified"
    target.write_text("user edit", encoding="utf-8")
    assert CoreRuntime(config_root).doctor()["host_installs"]["codex"] == "modified"
    with pytest.raises(ValueError, match="已被修改"):
        install_host(config_root, host_root, host="codex")
    with pytest.raises(ValueError, match="拒绝删除"):
        uninstall_host(config_root, host_root, host="codex")


def test_host_uninstall_removes_only_yushuos_managed_entry(tmp_path):
    source = copy_release_source(tmp_path / "source")
    config_root = tmp_path / "private-core"
    deploy(source, config_root, "0.2.0")
    host_root = tmp_path / "host" / ".workbuddy"
    old_entry = host_root / "rules" / "personal-system-core.md"
    old_entry.parent.mkdir(parents=True)
    old_entry.write_text("legacy entry remains available", encoding="utf-8")
    install_host(config_root, host_root, host="workbuddy")
    result = uninstall_host(config_root, host_root, host="workbuddy")
    assert result["removed"] is True
    assert old_entry.read_text(encoding="utf-8") == "legacy entry remains available"
    assert not (host_root / "rules" / "yushuos-core.md").exists()
