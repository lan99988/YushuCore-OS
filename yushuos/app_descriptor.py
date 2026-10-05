"""Strict App Descriptor v1 loader and normalizer.

Descriptors are portable policy metadata. Local credentials, account bindings,
release paths, and other machine-specific values belong outside this document.
"""

from pathlib import Path
import re
from typing import Any

from yushuos_sdk.canonical import canonical_bytes, loads

from .manifest import EFFECTS, _validate_schema_definition


_APP_ID = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9_-]*)*$")
_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9_-]*)*$")
_INTENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
_BINDING_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
_AUTH_SCOPE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_.:-]{0,99}|https?://[A-Za-z0-9.-]{1,255}(?:/[A-Za-z0-9._~!$&'()*+,;=:@%-]*)*)$")
_SECRET_KEY_SUFFIXES = (
    "password", "passwd", "secret", "token", "credential", "credentials", "apikey",
    "privatekey", "authorization", "cookie",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}"),
    re.compile(r"(?i)\b(?:access|refresh|client|api)?[_ -]?(?:token|secret|password|credential)s?\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)-----BEGIN\s+(?:[A-Z0-9 ]+\s+)?PRIVATE KEY-----"),
)
_MAX_DESCRIPTOR_BYTES = 1024 * 1024


def _reject_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(normalized_key.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES):
                raise ValueError("App Descriptor 禁止包含凭据字段")
            _reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_credentials(item)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        raise ValueError("App Descriptor 禁止包含凭据正文")


def _safe_binding_name(value: Any) -> bool:
    return (isinstance(value, str) and _BINDING_KEY.fullmatch(value) is not None
            and ".." not in value and not value.endswith("."))


def _schema(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} 必须是 Schema 对象")
    try:
        _validate_schema_definition(value, name)
    except (TypeError, ValueError, RecursionError):
        raise ValueError(f"{name} 无效") from None
    return value


def validate_app_descriptor(value: Any) -> dict[str, Any]:
    """Validate and return normalized App Descriptor v1 JSON data."""
    try:
        descriptor = loads(canonical_bytes(value))
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ValueError("App Descriptor 必须是安全的 JSON 数据") from None
    if not isinstance(descriptor, dict):
        raise ValueError("App Descriptor 根节点必须是对象")
    _reject_credentials(descriptor)

    if set(descriptor) != {"schema_version", "app", "version", "capabilities"}:
        raise ValueError("App Descriptor 字段不完整或包含未知字段")
    if type(descriptor["schema_version"]) is not int or descriptor["schema_version"] != 1:
        raise ValueError("App Descriptor schema_version 必须是 1")
    app = descriptor["app"]
    version = descriptor["version"]
    if not isinstance(app, str) or not _APP_ID.fullmatch(app):
        raise ValueError("App Descriptor app 格式无效")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("App Descriptor version 格式无效")
    capabilities = descriptor["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("App Descriptor 必须声明至少一项能力")

    required = {
        "id", "effect", "intent", "input_schema", "output_schema", "execution_mode", "auth", "resource_bindings",
    }
    allowed = required | {"description"}
    seen: set[str] = set()
    normalized_capabilities: list[dict[str, Any]] = []
    for item in capabilities:
        if not isinstance(item, dict) or set(item) - allowed or required - set(item):
            raise ValueError("App Descriptor capability 字段不完整或包含未知字段")
        capability_id = item["id"]
        if not isinstance(capability_id, str) or not _CAPABILITY_ID.fullmatch(capability_id) or capability_id in seen:
            raise ValueError("App Descriptor capability id 无效或重复")
        seen.add(capability_id)

        effect = item["effect"]
        if not isinstance(effect, str) or effect not in EFFECTS:
            raise ValueError(f"能力 {capability_id} 的 effect 无效")
        intent = item["intent"]
        if not isinstance(intent, str) or not _INTENT.fullmatch(intent):
            raise ValueError(f"能力 {capability_id} 的 intent 无效")
        execution_mode = item["execution_mode"]
        if not isinstance(execution_mode, str) or execution_mode not in {"standalone", "host_required"}:
            raise ValueError(f"能力 {capability_id} 的 execution_mode 无效")
        description = item.get("description", "")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError(f"能力 {capability_id} 的 description 无效")

        input_schema = _schema(item["input_schema"], f"能力 {capability_id} input_schema")
        output_schema = _schema(item["output_schema"], f"能力 {capability_id} output_schema")
        auth = item["auth"]
        if (not isinstance(auth, dict) or set(auth) != {"required", "scopes"}
                or type(auth["required"]) is not bool):
            raise ValueError(f"能力 {capability_id} 的 auth 格式无效")
        scopes = auth["scopes"]
        if (not isinstance(scopes, list) or any(not isinstance(scope, str)
                                                or len(scope) > 300 or not _AUTH_SCOPE.fullmatch(scope)
                                                for scope in scopes)
                or len(scopes) != len(set(scopes))):
            raise ValueError(f"能力 {capability_id} 的 auth.scopes 必须是不重复字符串数组")

        bindings = item["resource_bindings"]
        if not isinstance(bindings, dict) or any(
            not _safe_binding_name(key) or not _safe_binding_name(resource)
            for key, resource in bindings.items()
        ):
            raise ValueError(f"能力 {capability_id} 的 resource_bindings 包含无效或路径型名称")
        input_properties = input_schema.get("properties", {})
        if (bindings and input_schema.get("type", "object") != "object") or not set(bindings) <= set(input_properties):
            raise ValueError(f"能力 {capability_id} 的 resource_bindings 必须引用 input_schema 字段")

        normalized_capabilities.append({
            "id": capability_id,
            "description": description,
            "effect": effect,
            "intent": intent,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_mode": execution_mode,
            "auth": {"required": auth["required"], "scopes": sorted(scopes)},
            "resource_bindings": dict(sorted(bindings.items())),
        })

    normalized_capabilities.sort(key=lambda capability: capability["id"])
    return {
        "schema_version": 1,
        "app": app,
        "version": version,
        "capabilities": normalized_capabilities,
    }


def load_app_descriptor(path: str | Path) -> dict[str, Any]:
    """Load a UTF-8 JSON descriptor after checking the file and every parent path."""
    try:
        original_path = Path(path).expanduser().absolute()
        descriptor_path = original_path.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        raise ValueError("App Descriptor 文件不可用或 JSON 无效") from None
    for candidate in (original_path, *original_path.parents):
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise ValueError("App Descriptor 路径不允许链接")
    if not descriptor_path.is_file():
        raise ValueError("App Descriptor 必须是普通文件")
    try:
        size = descriptor_path.stat().st_size
    except OSError:
        raise ValueError("App Descriptor 文件不可用或 JSON 无效") from None
    if size > _MAX_DESCRIPTOR_BYTES:
        raise ValueError("App Descriptor 超过大小限制")
    try:
        raw = loads(descriptor_path.read_bytes())
    except (OSError, TypeError, ValueError, UnicodeError):
        raise ValueError("App Descriptor 文件不可用或 JSON 无效") from None
    return validate_app_descriptor(raw)


__all__ = ["load_app_descriptor", "validate_app_descriptor"]
