"""Versioned, strict plugin manifest parsing."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any

import yaml


PLUGIN_TYPES = frozenset({"domain", "app", "flow", "storage"})
EFFECTS = frozenset({"read_only", "proposal", "internal_write", "external_write"})
CAPABILITY_STATES = frozenset({"registered", "implemented", "verified", "authorized", "enabled"})
_ID = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9_-]*)*$")


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    effect: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    dependencies: tuple[str, ...]
    permissions: tuple[str, ...]
    intents: tuple[str, ...]
    implemented: bool
    verified: bool
    authorized: bool
    enabled: bool
    runner_args: tuple[str, ...] = ()
    resource_scopes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RouteSpec:
    prefix: str
    capability: str
    intent: str
    strip_prefix: bool
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginSpec:
    plugin_id: str
    name: str
    version: str
    contract_version: int
    plugin_type: str
    enabled: bool
    description: str
    root: Path
    dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    permissions: tuple[str, ...]
    data_path: str
    supported_runtimes: tuple[str, ...]
    configuration: dict[str, Any]
    error_policy: str
    audit_policy: str
    runner: dict[str, Any]
    package_hash_verified: bool
    capabilities: tuple[CapabilitySpec, ...]
    routes: tuple[RouteSpec, ...]
    skill_names: tuple[str, ...]


def _sequence(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} 必须是字符串数组")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} 不能有重复项")
    return tuple(value)


def _resource_scopes(value: Any, name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or any(
        not isinstance(field, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,99}", field)
        or not isinstance(scope, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,99}", scope)
        for field, scope in value.items()
    ):
        raise ValueError(f"{name}.resource_scopes 必须是目标字段到配置资源键的映射")
    return tuple(sorted(value.items()))


def _validate_schema_definition(schema: Any, name: str, *, depth: int = 0) -> None:
    if depth > 16 or not isinstance(schema, dict):
        raise ValueError(f"{name} Schema 层级或类型无效")
    allowed = {"type", "required", "properties", "additionalProperties", "items", "enum",
               "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}
    if set(schema) - allowed:
        raise ValueError(f"{name} Schema 包含不支持的字段")
    value_type = schema.get("type", "object")
    if not isinstance(value_type, str) or value_type not in {"any", "object", "string", "integer", "number", "boolean", "array"}:
        raise ValueError(f"{name} Schema 类型无效")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or any(not isinstance(key, str) for key in properties):
        raise ValueError(f"{name} Schema properties 必须是字符串键对象")
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required) or len(required) != len(set(required)) or not set(required) <= set(properties):
        raise ValueError(f"{name} Schema required 必须引用 properties 中的不重复字段")
    if type(schema.get("additionalProperties", True)) is not bool:
        raise ValueError(f"{name} Schema additionalProperties 必须是布尔值")
    for key, child in properties.items():
        _validate_schema_definition(child, f"{name}.{key}", depth=depth + 1)
    if "items" in schema:
        _validate_schema_definition(schema["items"], f"{name}[]", depth=depth + 1)
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise ValueError(f"{name} Schema {key} 必须是非负整数")
    for key in ("minimum", "maximum"):
        if key in schema and (type(schema[key]) not in {int, float} or not math.isfinite(schema[key])):
            raise ValueError(f"{name} Schema {key} 必须是有限数字")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise ValueError(f"{name} Schema enum 必须是数组")
    try:
        json.dumps(schema, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} Schema 必须是 JSON 数据") from exc


def validate_schema(schema: dict[str, Any], value: Any, *, path: str = "请求") -> str:
    """Validate the manifest-supported JSON Schema subset."""
    expected = schema.get("type", "object")
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    typ = types.get(expected)
    if expected != "any" and (typ is None or not isinstance(value, typ) or expected in {"integer", "number"} and isinstance(value, bool)):
        return f"{path} 类型无效，应为 {expected}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} 不在允许范围内"
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            return f"{path} 缺少必需字段：" + ", ".join(missing)
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                return f"{path} 包含不支持字段：" + ", ".join(sorted(extra))
        for key, item in value.items():
            if key in properties:
                error = validate_schema(properties[key], item, path=f"{path}.{key}")
                if error:
                    return error
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            return f"{path} 数组长度超出范围"
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                error = validate_schema(item_schema, item, path=f"{path}[{index}]")
                if error:
                    return error
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            return f"{path} 字符串长度超出范围"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            return f"{path} 数值超出范围"
    return ""


def load_manifest(path: str | Path, *, verify_lock: bool = True) -> PluginSpec:
    original_path = Path(path).expanduser().absolute()
    if original_path.is_symlink() or original_path.parent.is_symlink():
        raise ValueError("插件清单和插件目录不允许链接路径")
    manifest_path = original_path.resolve(strict=True)
    root = manifest_path.parent
    if manifest_path.name not in {"plugin.yaml", "plugin.yml"}:
        raise ValueError("插件清单文件名必须是 plugin.yaml")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("插件清单必须是普通文件")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("插件清单必须是对象")
    allowed = {
        "id", "name", "version", "contract_version", "type", "description", "enabled", "dependencies",
        "optional_dependencies", "permissions", "data_path", "supported_runtimes", "configuration",
        "error_policy", "audit_policy", "runner", "capabilities", "routes", "skill_names",
    }
    required = {"id", "name", "version", "contract_version", "type", "enabled", "dependencies", "permissions", "data_path", "runner", "capabilities"}
    if set(raw) - allowed or required - set(raw):
        raise ValueError("插件清单字段不完整或包含未知字段")
    plugin_id = raw["id"]
    version = raw["version"]
    if not isinstance(plugin_id, str) or not _ID.fullmatch(plugin_id):
        raise ValueError("插件 id 格式无效")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", version):
        raise ValueError("插件版本格式无效")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise ValueError("插件名称不能为空")
    if type(raw["contract_version"]) is not int or raw["contract_version"] != 2:
        raise ValueError("当前 Core 只接受 contract_version=2")
    if not isinstance(raw["type"], str) or raw["type"] not in PLUGIN_TYPES:
        raise ValueError("插件 type 无效")
    if type(raw["enabled"]) is not bool:
        raise ValueError("插件 enabled 必须是布尔值")
    data_path = raw["data_path"]
    if not isinstance(data_path, str):
        raise ValueError("data_path 必须是相对路径字符串")
    if data_path:
        data_rel = PurePosixPath(data_path.replace("\\", "/"))
        if data_rel.is_absolute() or ".." in data_rel.parts:
            raise ValueError("data_path 不得越出插件数据根目录")
    capabilities_raw = raw["capabilities"]
    if not isinstance(capabilities_raw, list) or not capabilities_raw:
        raise ValueError("插件必须登记至少一项能力")
    capabilities: list[CapabilitySpec] = []
    seen: set[str] = set()
    for item in capabilities_raw:
        if not isinstance(item, dict):
            raise ValueError("能力声明必须是对象")
        cap_allowed = {"name", "effect", "inputs", "outputs", "dependencies", "permissions", "intents", "implemented", "verified", "authorized", "enabled", "runner_args", "resource_scopes"}
        if set(item) - cap_allowed or not {"name", "effect"} <= set(item):
            raise ValueError("能力声明字段不完整或包含未知字段")
        name = item["name"]
        if not isinstance(name, str) or not _ID.fullmatch(name) or name in seen:
            raise ValueError("能力名称无效或重复")
        seen.add(name)
        effect = item["effect"]
        if not isinstance(effect, str) or effect not in EFFECTS:
            raise ValueError(f"能力 {name} 的 effect 无效")
        switches = {}
        for flag in ("implemented", "verified", "authorized", "enabled"):
            value = item.get(flag, flag == "implemented")
            if type(value) is not bool:
                raise ValueError(f"能力 {name} 的 {flag} 必须是布尔值")
            switches[flag] = value
        inputs, outputs = item.get("inputs", {}), item.get("outputs", {})
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise ValueError(f"能力 {name} 的输入与输出必须是对象")
        _validate_schema_definition(inputs, f"{name}.inputs")
        _validate_schema_definition(outputs, f"{name}.outputs")
        intents = _sequence(item.get("intents", []), f"{name}.intents")
        if not intents:
            raise ValueError(f"能力 {name} 必须声明至少一个允许意图")
        capabilities.append(CapabilitySpec(
            name=name, effect=effect, inputs=inputs, outputs=outputs,
            dependencies=_sequence(item.get("dependencies", []), f"{name}.dependencies"),
            permissions=_sequence(item.get("permissions", []), f"{name}.permissions"),
            intents=intents,
            runner_args=_sequence(item.get("runner_args", []), f"{name}.runner_args"),
            resource_scopes=_resource_scopes(item.get("resource_scopes", {}), name), **switches,
        ))
    routes_raw = raw.get("routes", [])
    if not isinstance(routes_raw, list):
        raise ValueError("routes 必须是数组")
    routes: list[RouteSpec] = []
    for route in routes_raw:
        if not isinstance(route, dict) or set(route) - {"prefix", "capability", "intent", "strip_prefix", "aliases"} or not {"prefix", "capability", "intent"} <= set(route):
            raise ValueError("路由声明字段不完整或包含未知字段")
        prefix, capability, intent = route["prefix"], route["capability"], route["intent"]
        if not isinstance(prefix, str) or not prefix.startswith("#") or not isinstance(capability, str) or capability not in seen or not isinstance(intent, str) or not intent:
            raise ValueError("路由前缀、能力或意图无效")
        strip_prefix = route.get("strip_prefix", True)
        if type(strip_prefix) is not bool:
            raise ValueError("strip_prefix 必须是布尔值")
        aliases = _sequence(route.get("aliases", []), f"{prefix}.aliases")
        if any(not alias.startswith("#") for alias in aliases) or prefix in aliases:
            raise ValueError("路由别名必须是不同的 # 前缀")
        routes.append(RouteSpec(prefix, capability, intent, strip_prefix, aliases))
    supported_runtimes = _sequence(raw.get("supported_runtimes", ["python>=3.11"]), "supported_runtimes")
    if not supported_runtimes or any(not re.fullmatch(r"python>=\d+\.\d+", item) for item in supported_runtimes):
        raise ValueError("V0.2 supported_runtimes 只接受 python>=主版本.次版本")
    configuration = raw.get("configuration", {"type": "object", "additionalProperties": False})
    _validate_schema_definition(configuration, "configuration")
    error_policy = raw.get("error_policy", "fail_closed")
    audit_policy = raw.get("audit_policy", "metadata_only")
    if error_policy != "fail_closed" or audit_policy != "metadata_only":
        raise ValueError("V0.2 只支持 fail_closed 错误策略和 metadata_only 审计策略")
    runner = raw.get("runner", {})
    if not isinstance(runner, dict) or set(runner) - {"command", "timeout_seconds", "protocol"}:
        raise ValueError("runner 配置格式无效")
    command = runner.get("command", [])
    if not isinstance(command, list) or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("runner.command 必须是字符串参数数组")
    timeout = runner.get("timeout_seconds", 90)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("runner.timeout_seconds 必须介于 1 到 3600 秒")
    protocol = runner.get("protocol", "json-stdio-v1")
    if protocol != "json-stdio-v1":
        raise ValueError("当前只支持 json-stdio-v1")
    skill_names = _sequence(raw.get("skill_names", []), "skill_names")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", item) for item in skill_names):
        raise ValueError("skill_names 包含无效名称")
    package_hash_verified = False
    lock_path = root / "plugin.lock.json"
    if verify_lock and lock_path.is_file() and not lock_path.is_symlink():
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        expected = lock.get("files") if isinstance(lock, dict) else None
        if (not isinstance(lock, dict) or set(lock) != {"format", "plugin_id", "version", "files"}
                or lock.get("format") != 1 or lock.get("plugin_id") != plugin_id
                or lock.get("version") != version or not isinstance(expected, dict)):
            raise ValueError("插件锁定清单和版本不匹配")
        actual: dict[str, str] = {}
        for file_path in root.rglob("*"):
            if file_path.is_symlink():
                raise ValueError("插件包不允许包含链接路径")
            if not file_path.is_file() or file_path == lock_path:
                continue
            relative = file_path.relative_to(root).as_posix()
            if relative in {"__pycache__"} or "__pycache__" in file_path.relative_to(root).parts:
                continue
            actual[relative] = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("插件文件与 SHA256 锁定清单不一致")
        package_hash_verified = True
    return PluginSpec(
        plugin_id=plugin_id, name=raw["name"], version=version, contract_version=2,
        plugin_type=raw["type"], enabled=raw["enabled"], description=raw.get("description", ""), root=root,
        dependencies=_sequence(raw.get("dependencies", []), "dependencies"),
        optional_dependencies=_sequence(raw.get("optional_dependencies", []), "optional_dependencies"),
        permissions=_sequence(raw["permissions"], "permissions"), data_path=data_path,
        supported_runtimes=supported_runtimes, configuration=configuration,
        error_policy=error_policy, audit_policy=audit_policy,
        runner={**runner, "command": command, "timeout_seconds": timeout, "protocol": protocol},
        package_hash_verified=package_hash_verified,
        capabilities=tuple(capabilities), routes=tuple(routes), skill_names=skill_names,
    )
