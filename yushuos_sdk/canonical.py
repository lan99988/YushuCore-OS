"""Strict JSON canonicalization and stable, domain-separated identifiers."""

from datetime import datetime, timezone
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import rfc8785


_MAX_SAFE_INTEGER = (1 << 53) - 1


def _check_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("JSON 字符串包含非法 Unicode")


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        _check_string(value)
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("JSON 整数超出安全范围")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON 数字必须是有限值")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON 对象键必须是字符串")
            _check_string(key)
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise ValueError("值不是受支持的 JSON 数据")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 对象包含重复键")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("JSON 包含非有限数字")


def loads(data: str | bytes) -> Any:
    """Parse strict UTF-8 JSON, rejecting duplicate keys and non-JCS values."""
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="strict")
        if not isinstance(data, str):
            raise ValueError
        parsed = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _normalize(parsed)
        return parsed
    except (TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("JSON 数据无效") from None


def canonical_bytes(value: Any) -> bytes:
    """Return RFC 8785 JCS bytes for safe JSON data."""
    try:
        return rfc8785.dumps(_normalize(value))
    except (TypeError, ValueError, UnicodeError, OverflowError):
        raise ValueError("JSON 规范化失败") from None


def digest(value: Any) -> str:
    """Return the lowercase SHA-256 digest of the value's JCS representation."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def timestamp(value: datetime | str) -> str:
    """Convert an aware datetime or ISO 8601 timestamp to UTC with six digits."""
    try:
        if isinstance(value, str):
            source = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
            value = datetime.fromisoformat(source)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        utc = value.astimezone(timezone.utc)
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("时间戳必须是带时区的 datetime 或 ISO 8601 字符串") from None


def run_id(rule_id: str, revision: str | int, occurrence_key: Any) -> str:
    """Build a full, domain-separated run ID from its stable identity fields."""
    if not isinstance(rule_id, str) or not rule_id or not isinstance(revision, (str, int)) or isinstance(revision, bool):
        raise ValueError("规则标识或修订无效")
    if isinstance(revision, str) and not revision:
        raise ValueError("规则标识或修订无效")
    return "run-" + digest({
        "kind": "run-v1",
        "rule_id": rule_id,
        "rule_revision": revision,
        "occurrence_key": occurrence_key,
    })


def request_id(run_id: str, step_id: str) -> str:
    """Build a full request ID in a domain separate from run IDs."""
    if (not isinstance(run_id, str) or not run_id.startswith("run-") or len(run_id) != 68
            or any(character not in "0123456789abcdef" for character in run_id[4:])):
        raise ValueError("run_id 必须是规范 run- SHA-256 标识")
    if not isinstance(step_id, str) or not step_id:
        raise ValueError("step_id 不能为空")
    return "req-" + digest({"kind": "step-v1", "run_id": run_id, "step_id": step_id})


__all__ = ["loads", "canonical_bytes", "digest", "timestamp", "run_id", "request_id"]
