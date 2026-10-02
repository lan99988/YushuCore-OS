"""Stable JSON contract available without installing the YushuOS runtime."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Mapping


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("对象键必须是字符串")
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise ValueError("数字必须是有限值")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError("请求只支持 JSON 数据")


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class Request:
    request_id: str
    capability: str
    intent: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    target: Mapping[str, Any] = field(default_factory=dict)
    project_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not _ID.fullmatch(self.request_id):
            raise ValueError("request_id 必须是稳定的非空标识")
        if not isinstance(self.capability, str) or not _ID.fullmatch(self.capability):
            raise ValueError("capability 格式无效")
        if not isinstance(self.intent, str) or not self.intent.strip():
            raise ValueError("intent 不能为空")
        if not isinstance(self.fields, Mapping) or not isinstance(self.target, Mapping):
            raise ValueError("fields 和 target 必须是对象")
        if not isinstance(self.project_ref, str) or len(self.project_ref) > 200:
            raise ValueError("project_ref 格式无效")
        object.__setattr__(self, "fields", freeze(self.fields))
        object.__setattr__(self, "target", freeze(self.target))

    def to_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "capability": self.capability, "intent": self.intent,
                "fields": thaw(self.fields), "target": thaw(self.target), "project_ref": self.project_ref}

    def fingerprint(self) -> str:
        payload = {key: self.to_dict()[key] for key in ("capability", "intent", "fields", "target")}
        if self.project_ref:
            payload["project_ref"] = self.project_ref
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def resource_key(self) -> str:
        target = thaw(self.target)
        if target:
            # Deliberately preserves the V0.1 lock key convention.
            return json.dumps({"domain": self.capability.split(".", 1)[0], **target}, sort_keys=True)
        return f"request:{self.request_id}"


@dataclass(frozen=True)
class Result:
    status: str
    request_id: str
    message: str = ""
    resource: Mapping[str, Any] = field(default_factory=dict)
    data: Any = None
    error: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "request_id": self.request_id, "message": self.message,
                "resource": thaw(self.resource), "data": thaw(self.data),
                "error": thaw(self.error) if self.error is not None else None}
