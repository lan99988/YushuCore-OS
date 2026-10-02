"""Layered private configuration with host-level disable decisions."""

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "project_ref": "",
    "core": {"id": "yushuos", "api_version": 2, "default_mode": "preview"},
    "plugins": {
        "discovery": "manifests", "activation": "on_demand", "verify_release_hash": True,
        "reject_missing_dependencies": True, "reject_dependency_cycles": True,
        "preserve_user_disabled": True, "plugin_paths": [], "disabled": [], "versions": {}, "config": {},
    },
    "routing": {"prefix_source": "plugin_manifests", "prefix_match": "longest_first", "natural_language": "host", "ambiguity": "clarify"},
    "context": {"loading": "on_demand", "persist_business_content": False},
    "execution": {
        "writes_require_explicit_intent": True, "preview_business_writes": False,
        "unknown_result_retry": False, "workflow_resume": "receipts", "automation_grants": "explicit_scope",
    },
    "state": {"ledger_path": ""},
    "hosts": {"workbuddy": True, "codex": True},
    "bindings": {"providers": {}, "resources": {}, "apps": {}},
    "permissions": {"grants": [], "denials": []},
    "runtime": {"python_executable": "", "available_dependencies": []},
    "user_disabled": [],
}

_BOOL_PATHS = (
    "plugins.verify_release_hash", "plugins.reject_missing_dependencies", "plugins.reject_dependency_cycles",
    "plugins.preserve_user_disabled", "context.persist_business_content", "execution.writes_require_explicit_intent",
    "execution.preview_business_writes", "execution.unknown_result_retry", "hosts.workbuddy", "hosts.codex",
)


def default_root() -> Path:
    value = os.environ.get("YUSHUOS_HOME")
    return Path(value).expanduser().absolute() if value else Path.home() / ".yushuos"


def _read_yaml(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ValueError(f"配置文件不存在：{path.name}")
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"配置必须是普通文件：{path.name}")
    value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"配置根节点必须是对象：{path.name}")
    return value


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _validate(config: dict[str, Any]) -> None:
    allowed = {"schema_version", "project_ref", "core", "plugins", "routing", "context", "execution", "state", "hosts", "bindings", "permissions", "runtime", "user_disabled"}
    if set(config) - allowed:
        raise ValueError("配置包含未知顶层字段")
    section_fields = {
        "core": {"id", "api_version", "default_mode"},
        "plugins": {"discovery", "activation", "verify_release_hash", "reject_missing_dependencies", "reject_dependency_cycles", "preserve_user_disabled", "plugin_paths", "disabled", "versions", "config"},
        "routing": {"prefix_source", "prefix_match", "natural_language", "ambiguity"},
        "context": {"loading", "persist_business_content"},
        "execution": {"writes_require_explicit_intent", "preview_business_writes", "unknown_result_retry", "workflow_resume", "automation_grants"},
        "state": {"ledger_path"}, "hosts": {"workbuddy", "codex"},
        "bindings": {"providers", "resources", "apps"}, "permissions": {"grants", "denials"},
        "runtime": {"python_executable", "available_dependencies"},
    }
    for section, fields in section_fields.items():
        value = config.get(section)
        if not isinstance(value, dict) or set(value) - fields:
            raise ValueError(f"配置 {section} 必须是已知字段组成的对象")
    if config.get("schema_version") != 1:
        raise ValueError("不支持的配置 schema_version")
    if not isinstance(config.get("project_ref"), str) or len(config["project_ref"]) > 200:
        raise ValueError("project_ref 必须是长度不超过 200 的字符串")
    if config.get("core", {}).get("id") != "yushuos" or config.get("core", {}).get("api_version") != 2:
        raise ValueError("配置中的本体标识或 API 版本不匹配")
    if config.get("core", {}).get("default_mode") not in {"preview", "readonly"}:
        raise ValueError("default_mode 仅允许 preview 或 readonly")
    if config.get("plugins", {}).get("activation") != "on_demand":
        raise ValueError("插件必须按需加载")
    plugins = config["plugins"]
    if (plugins.get("discovery") != "manifests" or plugins.get("reject_missing_dependencies") is not True
            or plugins.get("reject_dependency_cycles") is not True or plugins.get("preserve_user_disabled") is not True):
        raise ValueError("插件发现必须使用清单，并阻断缺失依赖、循环依赖和用户停用项")
    routing = config["routing"]
    if (routing.get("prefix_source") != "plugin_manifests" or routing.get("natural_language") != "host"
            or routing.get("prefix_match") != "longest_first" or routing.get("ambiguity") != "clarify"):
        raise ValueError("路由必须使用最长前缀和歧义澄清")
    if config.get("context", {}).get("loading") != "on_demand" or config.get("context", {}).get("persist_business_content") is not False:
        raise ValueError("上下文必须按需加载且不得写入业务正文")
    execution = config.get("execution", {})
    if (execution.get("writes_require_explicit_intent") is not True
            or execution.get("preview_business_writes") is not False
            or execution.get("unknown_result_retry") is not False
            or execution.get("automation_grants") != "explicit_scope"):
        raise ValueError("写入必须要求显式意图，预览和未知结果重试必须关闭，自动化按作用范围授权")
    if config.get("execution", {}).get("workflow_resume") != "receipts":
        raise ValueError("流程恢复必须依赖已有收据")
    for dotted in _BOOL_PATHS:
        current: Any = config
        for key in dotted.split("."):
            current = current.get(key) if isinstance(current, dict) else None
        if type(current) is not bool:
            raise ValueError(f"配置 {dotted} 必须是布尔值")
    for dotted in ("plugins.disabled", "user_disabled", "permissions.grants", "permissions.denials", "runtime.available_dependencies", "plugins.plugin_paths"):
        current = config
        for key in dotted.split("."):
            current = current.get(key) if isinstance(current, dict) else None
        if not isinstance(current, list) or any(not isinstance(item, str) or not item.strip() for item in current):
            raise ValueError(f"配置 {dotted} 必须是字符串数组")
    for dotted in ("plugins.versions", "bindings.providers", "bindings.resources"):
        current = config
        for key in dotted.split("."):
            current = current.get(key) if isinstance(current, dict) else None
        if not isinstance(current, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in current.items()):
            raise ValueError(f"配置 {dotted} 必须是字符串键对象")
    plugin_config = config.get("plugins", {}).get("config")
    if not isinstance(plugin_config, dict):
        raise ValueError("配置 plugins.config 必须是对象")
    for plugin_id, value in plugin_config.items():
        if not isinstance(plugin_id, str) or not plugin_id.strip() or len(plugin_id) > 200 or not isinstance(value, dict):
            raise ValueError("配置 plugins.config 必须按插件 ID 映射对象")
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("配置 plugins.config 必须只包含有限 JSON 数据") from exc
        if len(encoded.encode("utf-8")) > 131072:
            raise ValueError("单个插件项目配置不得超过 128 KiB")
    apps = config["bindings"].get("apps")
    if not isinstance(apps, dict):
        raise ValueError("配置 bindings.apps 必须是插件绑定对象")
    for plugin_id, binding in apps.items():
        if (not isinstance(plugin_id, str) or not isinstance(binding, dict)
                or set(binding) != {"active_pointer"} or not isinstance(binding["active_pointer"], str)
                or not Path(binding["active_pointer"]).expanduser().is_absolute()):
            raise ValueError("每个 bindings.apps 项只能包含绝对路径 active_pointer")
    if not isinstance(config["state"].get("ledger_path"), str):
        raise ValueError("state.ledger_path 必须是字符串")
    if not isinstance(config["runtime"].get("python_executable"), str):
        raise ValueError("runtime.python_executable 必须是字符串")


def _host_disabled(config_root: Path) -> set[str]:
    roots = {Path.home() / ".workbuddy", Path.home() / ".codex"}
    env_root = os.environ.get("CODEBUDDY_CONFIG_DIR")
    if env_root:
        roots.add(Path(env_root).expanduser())
    roots.add(config_root)
    disabled: set[str] = set()
    for root in roots:
        settings = root / "settings.json"
        if not settings.is_file() or settings.is_symlink():
            continue
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        overrides = data.get("skillOverrides", {}) if isinstance(data, dict) else {}
        if isinstance(overrides, dict):
            disabled.update(name for name, state in overrides.items() if state == "off")
    return disabled


def load_config(config_root: str | Path | None = None, *, project_file: str | Path | None = None) -> dict[str, Any]:
    root = Path(config_root).expanduser().absolute() if config_root else default_root()
    base = _read_yaml(root / "config.yaml")
    config = _merge(DEFAULTS, base)
    bindings_dir = root / "bindings.d"
    if bindings_dir.exists():
        if bindings_dir.is_symlink() or not bindings_dir.is_dir():
            raise ValueError("bindings.d 必须是普通目录")
        for binding_file in sorted(bindings_dir.glob("*.yaml")):
            overlay = _read_yaml(binding_file, required=True)
            if set(overlay) - {"schema_version", "plugins", "bindings"} or overlay.get("schema_version", 1) != 1:
                raise ValueError("独立绑定文件只能配置插件版本和 App 活动指针")
            plugins = overlay.get("plugins", {})
            bindings = overlay.get("bindings", {})
            if not isinstance(plugins, dict) or set(plugins) - {"versions"}:
                raise ValueError("独立绑定文件不得修改插件安全策略")
            versions = plugins.get("versions", {})
            if not isinstance(versions, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in versions.items()):
                raise ValueError("独立绑定文件 plugins.versions 格式无效")
            if not isinstance(bindings, dict) or set(bindings) - {"apps"}:
                raise ValueError("独立绑定文件不得修改能力提供者或权限")
            apps = bindings.get("apps", {})
            if not isinstance(apps, dict) or any(
                not isinstance(key, str) or not isinstance(value, dict) or set(value) != {"active_pointer"}
                or not isinstance(value["active_pointer"], str) or not Path(value["active_pointer"]).expanduser().is_absolute()
                for key, value in apps.items()
            ):
                raise ValueError("独立绑定文件 bindings.apps 格式无效")
            config = _merge(config, overlay)
    project_disabled: set[str] = set()
    if project_file:
        project = _read_yaml(Path(project_file).expanduser().absolute(), required=True)
        if project.get("schema_version") not in (None, 1):
            raise ValueError("不支持的项目配置 schema_version")
        if set(project) - {"schema_version", "project_ref", "plugins", "bindings"}:
            raise ValueError("项目配置包含不允许覆盖的顶层字段")
        if "project_ref" in project and (not isinstance(project["project_ref"], str) or len(project["project_ref"]) > 200):
            raise ValueError("项目 project_ref 格式无效")
        for section, allowed_keys in {"plugins": {"disabled", "versions", "plugin_paths", "config"}, "bindings": {"providers", "resources"}}.items():
            value = project.get(section, {})
            if not isinstance(value, dict) or set(value) - allowed_keys:
                raise ValueError(f"项目配置 {section} 包含不允许覆盖的字段")
            if section == "plugins":
                for key in ("disabled", "plugin_paths"):
                    items = value.get(key, [])
                    if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                        raise ValueError(f"项目配置 plugins.{key} 必须是字符串数组")
                versions = value.get("versions", {})
                if not isinstance(versions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in versions.items()):
                    raise ValueError("项目配置 plugins.versions 必须是字符串键对象")
                plugin_config = value.get("config", {})
                if not isinstance(plugin_config, dict) or any(not isinstance(k, str) or not isinstance(v, dict) for k, v in plugin_config.items()):
                    raise ValueError("项目配置 plugins.config 必须是插件 ID 到对象的映射")
                for config_value in plugin_config.values():
                    try:
                        encoded = json.dumps(config_value, ensure_ascii=False, allow_nan=False)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("项目插件配置必须只包含有限 JSON 数据") from exc
                    if len(encoded.encode("utf-8")) > 131072:
                        raise ValueError("单个插件项目配置不得超过 128 KiB")
            if section == "bindings":
                for key in allowed_keys:
                    items = value.get(key, {})
                    if not isinstance(items, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in items.items()):
                        raise ValueError(f"项目配置 bindings.{key} 必须是字符串键对象")
        project_disabled.update(project.get("plugins", {}).get("disabled", []))
        config = _merge(config, project)
    # User and host decisions are monotonic: project configuration cannot reopen them.
    base_config = base
    user_disabled = set(base_config.get("user_disabled", []))
    user_disabled.update(base_config.get("plugins", {}).get("disabled", []))
    user_disabled.update(project_disabled)
    user_disabled.update(_host_disabled(root))
    config["user_disabled"] = sorted(user_disabled)
    _validate(config)
    config["_config_root"] = str(root.resolve())
    config["_project_file"] = str(Path(project_file).expanduser().absolute()) if project_file else ""
    return config
