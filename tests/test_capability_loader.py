from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from capability_plugins.registry import PluginRegistry


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "capability_plugins"
MANIFESTS_DIR = PACKAGE_DIR / "manifests"

REQUIRED_FIELDS = {
    "plugin_id",
    "name",
    "version",
    "purpose",
    "domain",
    "provides",
    "reads",
    "writes",
    "dependencies",
    "permissions",
    "risk_level",
    "activation_mode",
    "availability",
    "enabled",
    "activation_state",
}

CORE_PLUGIN_IDS = {"task", "knowledge", "information"}
BUILTIN_PLUGIN_IDS = {
    "task",
    "calendar",
    "project",
    "goal",
    "learning",
    "knowledge",
    "body",
    "information",
    "social",
    "life_admin",
    "finance",
    "creation",
    "interest",
    "experience",
    "local_record",
}


def _loader():
    assert (PACKAGE_DIR / "loader.py").is_file(), "capability manifest loader is missing"
    return importlib.import_module("capability_plugins.loader")


def _manifest(plugin_id: str = "example", **overrides):
    data = {
        "plugin_id": plugin_id,
        "name": f"{plugin_id.title()} Plugin",
        "version": "1.0.0",
        "purpose": "声明一个现有能力",
        "domain": plugin_id,
        "provides": [f"{plugin_id}.read"],
        "reads": [],
        "writes": [],
        "dependencies": [],
        "permissions": [],
        "risk_level": "low",
        "activation_mode": "on_demand",
        "availability": "installed",
        "enabled": True,
        "activation_state": "dormant",
    }
    data.update(overrides)
    return data


def _write_manifest(directory: Path, filename: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_load_manifests_uses_injected_directory_and_stable_filename_order(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "20_beta.yaml", _manifest("beta"))
    _write_manifest(tmp_path, "01_中文.yaml", _manifest("alpha", purpose="读取中文声明"))

    manifests = loader.load_manifests(tmp_path)

    assert isinstance(manifests, tuple)
    assert tuple(item.plugin_id for item in manifests) == ("alpha", "beta")
    assert manifests[0].purpose == "读取中文声明"


def test_load_manifests_rejects_missing_directory(tmp_path):
    loader = _loader()

    with pytest.raises(FileNotFoundError, match="manifest directory"):
        loader.load_manifests(tmp_path / "missing")


def test_load_manifests_rejects_directory_without_yaml(tmp_path):
    loader = _loader()

    with pytest.raises(ValueError, match="no manifest"):
        loader.load_manifests(tmp_path)


def test_builtin_manifests_declare_all_supported_domains():
    loader = _loader()

    manifests = loader.load_manifests(MANIFESTS_DIR)

    assert tuple(item.plugin_id for item in manifests) == tuple(sorted(BUILTIN_PLUGIN_IDS))
    assert len(manifests) == len(BUILTIN_PLUGIN_IDS)
    for path in MANIFESTS_DIR.glob("*.yaml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert REQUIRED_FIELDS <= set(payload)

    by_id = {item.plugin_id: item for item in manifests}
    for plugin_id in CORE_PLUGIN_IDS:
        manifest = by_id[plugin_id]
        assert manifest.provides
        assert manifest.availability.value == "installed"
        assert manifest.enabled is True
        assert manifest.activation_state.value == "active"
        assert manifest.activation_mode == "always"

    for manifest in manifests:
        if manifest.availability.value == "unavailable":
            assert manifest.provides == ()
            assert manifest.enabled is False
            assert manifest.activation_state.value == "dormant"


def test_load_manifests_rejects_empty_file(tmp_path):
    loader = _loader()
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        loader.load_manifests(tmp_path)


@pytest.mark.parametrize("content", ["- one\n- two\n", "plain scalar\n"])
def test_load_manifests_rejects_non_mapping_yaml(tmp_path, content):
    loader = _loader()
    (tmp_path / "invalid.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        loader.load_manifests(tmp_path)


def test_load_manifests_uses_safe_yaml_loader(tmp_path):
    loader = _loader()
    (tmp_path / "unsafe.yaml").write_text(
        "!!python/object/apply:os.system ['echo unsafe']\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        loader.load_manifests(tmp_path)


def test_load_manifests_delegates_unknown_fields_to_manifest_converter(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "unknown.yaml", _manifest(module="os.system"))

    with pytest.raises(ValueError, match="unknown"):
        loader.load_manifests(tmp_path)


def test_load_manifests_rejects_duplicate_plugin_ids(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "a.yaml", _manifest("same"))
    _write_manifest(tmp_path, "b.yaml", _manifest("same"))

    with pytest.raises(ValueError, match="duplicate plugin_id"):
        loader.load_manifests(tmp_path)


def test_load_manifests_rejects_self_dependency(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "self.yaml", _manifest("self", dependencies=["self"]))

    with pytest.raises(ValueError, match="self-dependency"):
        loader.load_manifests(tmp_path)


def test_load_manifests_rejects_missing_dependency(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "dependent.yaml", _manifest("dependent", dependencies=["missing"]))

    with pytest.raises(ValueError, match="missing dependency"):
        loader.load_manifests(tmp_path)


def test_load_manifests_rejects_dependency_cycles(tmp_path):
    loader = _loader()
    _write_manifest(tmp_path, "a.yaml", _manifest("alpha", dependencies=["beta"]))
    _write_manifest(tmp_path, "b.yaml", _manifest("beta", dependencies=["alpha"]))

    with pytest.raises(ValueError, match="dependency cycle"):
        loader.load_manifests(tmp_path)


def test_yaml_priority_metadata_builds_unique_provider_selection(tmp_path):
    loader = _loader()
    capability = "shared.read"
    _write_manifest(
        tmp_path,
        "primary.yaml",
        _manifest(
            "primary",
            provides=[capability],
            activation_mode="always",
            activation_state="active",
            capability_priorities={capability: 10},
            capability_priority_reasons={capability: "primary_adapter"},
        ),
    )
    _write_manifest(
        tmp_path,
        "fallback.yaml",
        _manifest(
            "fallback",
            provides=[capability],
            activation_mode="always",
            activation_state="active",
            capability_priorities={capability: 1},
            capability_priority_reasons={capability: "fallback_adapter"},
        ),
    )

    registry = PluginRegistry.from_manifests(loader.load_manifests(tmp_path))

    assert registry.by_capability(capability).plugin_id == "primary"
