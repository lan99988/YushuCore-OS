from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import hashlib

import pytest
import yaml

from yushuos.config import load_config
from yushuos.deployment import lock_plugin
from yushuos.manifest import load_manifest
from yushuos.registry import PluginRegistry, provider_digest
from yushuos_sdk.contracts import Request


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "plugin-template"


def make_plugin(
    root: Path,
    *,
    plugin_id: str = "example.echo",
    version: str = "0.1.0",
    contract_version: int = 2,
    dependencies: list[str] | None = None,
    dependency_versions: dict[str, str] | None = None,
    emitted_events: list[str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    plugin = root / plugin_id
    shutil.copytree(TEMPLATE, plugin)
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["id"] = plugin_id
    manifest["version"] = version
    manifest["contract_version"] = contract_version
    if dependencies is not None:
        manifest["dependencies"] = dependencies
    if contract_version == 3:
        manifest["runner"]["protocol"] = "json-stdio-v2"
        manifest["capabilities"][0]["description"] = "Echoes the supplied message."
        manifest["capabilities"][0]["execution_mode"] = "standalone"
        manifest["emitted_events"] = emitted_events or []
        manifest["dependency_versions"] = dependency_versions or {}
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if contract_version == 3:
        files = {
            path.relative_to(plugin).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in plugin.rglob("*")
            if path.is_file() and path.name != "plugin.lock.json"
        }
        (plugin / "plugin.lock.json").write_text(
            json.dumps({"format": 1, "plugin_id": plugin_id, "version": version, "files": files}),
            encoding="utf-8",
        )
    else:
        lock_plugin(plugin)
    return plugin


def _registry_config(root: Path) -> dict:
    config = load_config(root)
    config.setdefault("_config_root", str(root))
    return config


def test_v2_defaults_and_still_rejects_v3_fields(tmp_path):
    plugin = make_plugin(tmp_path / "plugins")
    spec = load_manifest(plugin / "plugin.yaml")
    assert spec.contract_version == 2
    assert spec.runner["protocol"] == "json-stdio-v1"
    assert spec.capabilities[0].execution_mode == "host_required"
    assert spec.capabilities[0].description == ""

    manifest_path = plugin / "plugin.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["emitted_events"] = ["example.created"]
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="未知字段"):
        load_manifest(manifest_path, verify_lock=False)

    raw.pop("emitted_events")
    raw["capabilities"][0]["execution_mode"] = "standalone"
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="未知字段"):
        load_manifest(manifest_path, verify_lock=False)


def test_v3_parses_capability_execution_contract_and_exact_dependency_versions(tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    make_plugin(plugins, plugin_id="support.store", version="2.4.1")
    plugin = make_plugin(
        plugins,
        contract_version=3,
        dependencies=["support.store"],
        dependency_versions={"support.store": "2.4.1"},
        emitted_events=["example.echo.completed"],
    )

    spec = load_manifest(plugin / "plugin.yaml")
    assert spec.contract_version == 3
    assert spec.runner["protocol"] == "json-stdio-v2"
    assert spec.capabilities[0].description == "Echoes the supplied message."
    assert spec.capabilities[0].execution_mode == "standalone"
    assert spec.emitted_events == ("example.echo.completed",)
    assert dict(spec.dependency_versions) == {"support.store": "2.4.1"}


@pytest.mark.parametrize("execution_mode", ["", "hybrid", "standalone|host_required"])
def test_v3_rejects_execution_modes_outside_the_two_contract_values(tmp_path, execution_mode):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["capabilities"][0]["execution_mode"] = execution_mode
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="execution_mode"):
        load_manifest(manifest_path, verify_lock=False)


def test_v3_requires_capability_execution_mode(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["capabilities"][0].pop("execution_mode")
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="execution_mode"):
        load_manifest(manifest_path, verify_lock=False)


def test_v3_optional_events_versions_and_capability_description_have_defaults(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["description"] = "Plugin description."
    raw.pop("emitted_events")
    raw.pop("dependency_versions")
    raw["capabilities"][0].pop("description")
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    spec = load_manifest(manifest_path, verify_lock=False)
    assert spec.emitted_events == ()
    assert dict(spec.dependency_versions) == {}
    assert spec.capabilities[0].description == "Plugin description."


def test_v3_requires_json_stdio_v2_runner_protocol(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["runner"]["protocol"] = "json-stdio-v1"
    manifest_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="json-stdio-v2"):
        load_manifest(manifest_path, verify_lock=False)


def test_provider_digest_rechecks_locked_files_each_time(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    spec = load_manifest(plugin / "plugin.yaml")
    try:
        provider_digest = getattr(importlib.import_module("yushuos.registry"), "provider_digest")
    except ImportError:
        pytest.fail("required SDK module is missing: yushuos.registry.provider_digest")
    except AttributeError:
        pytest.fail("required API is missing: yushuos.registry.provider_digest")
    first = provider_digest(spec)
    assert re.fullmatch(r"[0-9a-f]{64}", first)

    runner = plugin / "run.py"
    runner.write_text(runner.read_text(encoding="utf-8") + "\n# changed after lock\n", encoding="utf-8")
    with pytest.raises(ValueError, match="锁定清单"):
        provider_digest(spec)

    lock_plugin(plugin)
    second = provider_digest(spec)
    assert second != first
    assert spec.version == "0.1.0"


def test_app_provider_digest_tracks_same_version_external_release_and_config(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", plugin_id="app-demo", version="1.2.3", contract_version=3)
    plugin_manifest = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))
    plugin_manifest["type"] = "app"
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(plugin_manifest), encoding="utf-8")
    lock_plugin(plugin)
    spec = load_manifest(plugin / "plugin.yaml")
    release = tmp_path / "app-release"
    entry = release / "app_plugins" / "__main__.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("print('version one')\n", encoding="utf-8")
    config_file = tmp_path / "app-config.json"
    config_file.write_text('{"access_token":"first-secret"}\n', encoding="utf-8")
    ledger = tmp_path / "ledger.sqlite"
    ledger.touch()
    python = tmp_path / "python.exe"
    python.write_bytes(b"stable-python-placeholder")

    def relock_release():
        files = {
            path.relative_to(release).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in release.rglob("*") if path.is_file() and path.name != "manifest.json"
        }
        (release / "manifest.json").write_text(json.dumps({
            "app": "demo", "version": "1.2.3", "files": files,
        }), encoding="utf-8")

    relock_release()
    pointer = tmp_path / "apps" / "demo" / "active.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({
        "app": "demo", "version": "1.2.3", "release": str(release),
        "config_file": str(config_file), "ledger_path": str(ledger),
        "python_executable": str(python),
    }), encoding="utf-8")
    config = {"bindings": {"apps": {"app-demo": {"active_pointer": str(pointer)}}}}

    first = provider_digest(spec, config)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert provider_digest(spec, {}) == provider_digest(spec)

    relocated = tmp_path / "relocated"
    relocated_release = relocated / "release"
    relocated_release.parent.mkdir()
    shutil.copytree(release, relocated_release)
    relocated_config = relocated / "app-config.json"
    shutil.copyfile(config_file, relocated_config)
    relocated_pointer = relocated / "apps" / "demo" / "active.json"
    relocated_pointer.parent.mkdir(parents=True)
    relocated_pointer.write_text(json.dumps({
        "app": "demo", "version": "1.2.3", "release": str(relocated_release),
        "config_file": str(relocated_config), "ledger_path": str(ledger),
        "python_executable": str(python),
    }), encoding="utf-8")
    relocated_binding = {"bindings": {"apps": {"app-demo": {"active_pointer": str(relocated_pointer)}}}}
    assert provider_digest(spec, relocated_binding) == first

    entry.write_text("print('version two')\n", encoding="utf-8")
    relock_release()
    second = provider_digest(spec, config)
    assert second != first

    config_file.write_text('{"access_token":"second-secret"}\n', encoding="utf-8")
    third = provider_digest(spec, config)
    assert third != second
    assert str(release) not in first + second + third
    assert "first-secret" not in first + second + third
    assert "second-secret" not in first + second + third


def test_dependency_version_mismatch_blocks_readiness(tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    make_plugin(plugins, plugin_id="support.store", version="2.4.2")
    consumer = make_plugin(
        plugins,
        contract_version=3,
        dependencies=["support.store"],
        dependency_versions={"support.store": "2.4.1"},
    )
    config = _registry_config(tmp_path)
    registry = PluginRegistry([plugins], config)
    binding = next(binding for binding in registry.providers("example.echo") if binding.plugin.plugin_id == "example.echo")
    assert not binding.ready
    assert "dependency_version_mismatch:support.store" in binding.reasons


@pytest.mark.parametrize("effect", ["read_only", "proposal"])
def test_v3_unauthorized_read_or_proposal_capability_is_blocked(tmp_path, effect):
    plugins = tmp_path / "plugins"
    plugin = make_plugin(plugins, contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"][0].update(effect=effect, authorized=False, permissions=[])
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    lock_plugin(plugin)

    registry = PluginRegistry([plugins], _registry_config(tmp_path))
    binding = registry.providers("example.echo")[0]
    assert not binding.ready
    assert "not_authorized" in binding.reasons


def test_v3_read_permissions_require_grant_but_unscoped_public_read_does_not(tmp_path):
    plugins = tmp_path / "plugins"
    plugin = make_plugin(plugins, contract_version=3)
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    capability = manifest["capabilities"][0]
    capability.update(effect="read_only", authorized=True, permissions=["example.read"])
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    lock_plugin(plugin)

    config = _registry_config(tmp_path)
    binding = PluginRegistry([plugins], config).providers("example.echo")[0]
    assert not binding.ready
    assert "permission_not_granted" in binding.reasons

    config["permissions"]["grants"] = ["example.read"]
    binding = PluginRegistry([plugins], config).providers("example.echo")[0]
    assert binding.ready

    capability["permissions"] = []
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    lock_plugin(plugin)
    public_binding = PluginRegistry([plugins], _registry_config(tmp_path)).providers("example.echo")[0]
    assert public_binding.ready


def test_v2_read_only_keeps_legacy_authorization_behavior(tmp_path):
    plugins = tmp_path / "plugins"
    plugin = make_plugin(plugins, contract_version=2)
    manifest_path = plugin / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"][0].update(authorized=False, permissions=["example.read"])
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    lock_plugin(plugin)

    binding = PluginRegistry([plugins], _registry_config(tmp_path)).providers("example.echo")[0]
    assert binding.ready


def test_catalog_details_preserve_legacy_shape_and_add_contract_fields(tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    make_plugin(plugins, contract_version=3, emitted_events=["example.echo.completed"])
    registry = PluginRegistry([plugins], _registry_config(tmp_path))

    legacy = registry.catalog()
    assert registry.catalog(details=False) == legacy
    plugin = legacy["plugins"][0]
    assert set(plugin) == {
        "id", "name", "version", "lifecycle_state", "supported_runtimes", "error_policy",
        "audit_policy", "type", "description", "capabilities",
    }
    assert set(plugin["capabilities"][0]) == {
        "name", "effect", "implemented", "verified", "authorized", "enabled", "available",
        "provider_selected", "ambiguous_provider", "unavailable_reasons",
    }

    detailed = registry.catalog(details=True)["plugins"][0]
    capability = detailed["capabilities"][0]
    assert capability["schema"] == {
        "inputs": load_manifest(plugins / "example.echo" / "plugin.yaml").capabilities[0].inputs,
        "outputs": load_manifest(plugins / "example.echo" / "plugin.yaml").capabilities[0].outputs,
    }
    assert capability["intents"] == ["read"]
    assert capability["execution_mode"] == "standalone"
    assert capability["resource_scopes"] == {}
    assert detailed["events"] == ["example.echo.completed"]
    assert detailed["dependency_versions"] == {}
    assert re.fullmatch(r"[0-9a-f]{64}", detailed["provider_digest"])


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        pytest.fail(f"required SDK module is missing: {name}")


def test_canonical_json_uses_jcs_and_hashes_canonical_bytes():
    canonical = _module("yushuos_sdk.canonical")
    value = {"z": [True, None, "€"], "a": {"n": 1.0, "negative_zero": -0.0}}
    expected = '{"a":{"n":1,"negative_zero":0},"z":[true,null,"€"]}'.encode("utf-8")
    assert canonical.canonical_bytes(value) == expected
    assert canonical.digest(value) == hashlib.sha256(expected).hexdigest()
    assert canonical.canonical_bytes({"b": 1e30, "a": 4.50, "c": 2e-3}) == b'{"a":4.5,"b":1e+30,"c":0.002}'


@pytest.mark.parametrize("payload", ['{"x":1,"x":2}', "NaN", "Infinity", "-Infinity"])
def test_canonical_loads_rejects_duplicate_keys_and_nonfinite_constants(payload):
    canonical = _module("yushuos_sdk.canonical")
    with pytest.raises(ValueError):
        canonical.loads(payload)


def test_canonical_errors_are_safe_and_domain_ids_are_stable_full_hashes():
    canonical = _module("yushuos_sdk.canonical")
    with pytest.raises(ValueError) as caught:
        canonical.canonical_bytes("\ud800")
    assert "\ud800" not in str(caught.value)
    with pytest.raises(ValueError):
        canonical.canonical_bytes(2**53)

    first = canonical.run_id("rule.alpha", "rev-digest", {"scheduled_for": "2026-10-05T01:02:03Z"})
    same = canonical.run_id("rule.alpha", "rev-digest", {"scheduled_for": "2026-10-05T01:02:03Z"})
    step = canonical.request_id(first, "step-1")
    assert first == same
    assert re.fullmatch(r"run-[0-9a-f]{64}", first)
    assert re.fullmatch(r"req-[0-9a-f]{64}", step)
    assert step != canonical.run_id("rule.alpha", "rev-digest", {"scheduled_for": "2026-10-05T01:02:03Z"})


def test_canonical_timestamp_converts_to_utc_with_six_fractional_digits():
    canonical = _module("yushuos_sdk.canonical")
    value = datetime(2026, 10, 5, 9, 2, 3, 1200, tzinfo=timezone.utc)
    assert canonical.timestamp(value) == "2026-10-05T09:02:03.001200Z"
    assert canonical.timestamp("2026-10-05T17:02:03.001200+08:00") == "2026-10-05T09:02:03.001200Z"


def test_v2_request_fingerprint_keeps_the_original_encoding():
    request = Request(
        "request-1", "example.echo", "read", {"message": "你好"}, {"target_id": "A"}, "project.demo"
    )
    original_body = {
        "capability": "example.echo",
        "intent": "read",
        "fields": {"message": "你好"},
        "target": {"target_id": "A"},
        "project_ref": "project.demo",
    }
    encoded = json.dumps(original_body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert request.fingerprint() == hashlib.sha256(encoded).hexdigest()


def test_plugin_context_reads_json_stdio_v2_and_rejects_mismatched_identity():
    context_module = _module("yushuos_sdk.context")
    payload = {
        "protocol": "json-stdio-v2",
        "plugin_id": "example.echo",
        "plugin_version": "0.1.0",
        "request": {"request_id": "request-1", "project_ref": "project.demo"},
        "context": {
            "schema_version": 1,
            "plugin_id": "example.echo",
            "plugin_version": "0.1.0",
            "provider_digest": "a" * 64,
            "project_ref": "project.demo",
            "request_id": "request-1",
            "state_ledger_path": "C:/state/ledger.sqlite",
            "data_path": "C:/data/example.echo",
            "emitted_events": ["example.echo.completed"],
            "run_id": "run-" + "b" * 64,
            "root_event_id": "event-root",
            "causation_id": "event-parent",
            "depth": 1,
            "mode": "execute",
            "host_mode": "execute",
            "resources": {"vault": {"path": "C:/vault"}},
        },
    }
    context = context_module.PluginContext.from_envelope(payload)
    assert context.plugin_id == "example.echo"
    assert context.emitted_events == ("example.echo.completed",)
    assert context.to_dict()["schema_version"] == 1
    with pytest.raises((AttributeError, TypeError)):
        context.plugin_id = "changed"

    payload["context"]["plugin_id"] = "example.other"
    with pytest.raises(ValueError, match="身份"):
        context_module.PluginContext.from_envelope(payload)


def test_detailed_catalog_uses_configured_app_identity(tmp_path, monkeypatch):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    config = _registry_config(tmp_path)
    registry = PluginRegistry([plugin.parent], config)
    seen = []
    def digest_with_binding(spec, supplied_config=None):
        seen.append(supplied_config)
        return "a" * 64 if supplied_config is config else "b" * 64
    monkeypatch.setattr("yushuos.registry.provider_digest", digest_with_binding)
    assert registry.catalog(details=True)["plugins"][0]["provider_digest"] == "a" * 64
    assert seen == [config]
