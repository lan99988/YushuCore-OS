"""Immutable, validated plugin context for json-stdio-v2 envelopes."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, ClassVar

from .canonical import canonical_bytes
from .contracts import freeze, thaw


_HEX_256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PluginContext:
    """Validated v1 context. Exposed values are recursively immutable."""

    _values: Mapping[str, Any]

    _FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "schema_version", "plugin_id", "plugin_version", "provider_digest", "project_ref", "request_id",
        "state_ledger_path", "data_path", "emitted_events", "run_id", "root_event_id", "causation_id",
        "depth", "mode", "host_mode", "resources", "intent", "operation_support", "fingerprint_scheme",
    )
    _V1_FIELD_NAMES: ClassVar[frozenset[str]] = frozenset(_FIELD_NAMES) - {"intent", "operation_support", "fingerprint_scheme"}
    _STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "plugin_id", "plugin_version", "provider_digest", "project_ref", "request_id", "state_ledger_path",
        "data_path", "run_id", "root_event_id", "causation_id", "mode", "host_mode",
    )

    def __getattr__(self, name: str) -> Any:
        if name in self._FIELD_NAMES:
            return self._values.get(name)
        raise AttributeError(name)

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "PluginContext":
        if not isinstance(envelope, Mapping) or envelope.get("protocol") != "json-stdio-v2":
            raise ValueError("插件信封必须使用 json-stdio-v2")
        request = envelope.get("request")
        context = envelope.get("context")
        if not isinstance(request, Mapping) or not isinstance(context, Mapping):
            raise ValueError("插件信封缺少请求或上下文对象")
        schema_version = context.get("schema_version") if isinstance(context, Mapping) else None
        expected_fields = cls._V1_FIELD_NAMES if schema_version == 1 else cls._FIELD_NAMES
        if set(context) != set(expected_fields):
            raise ValueError("插件上下文字段不完整或包含未知字段")
        if type(schema_version) is not int or schema_version not in {1, 2}:
            raise ValueError("插件上下文 schema_version 无效")

        for key in cls._STRING_FIELDS:
            if not isinstance(context[key], str):
                raise ValueError(f"插件上下文 {key} 类型无效")
        if not _HEX_256.fullmatch(context["provider_digest"]):
            raise ValueError("插件上下文 provider_digest 无效")
        if not isinstance(context["emitted_events"], list) or any(
            not isinstance(event, str) or not event.strip() for event in context["emitted_events"]
        ) or len(context["emitted_events"]) != len(set(context["emitted_events"])):
            raise ValueError("插件上下文 emitted_events 必须是不重复字符串数组")
        if type(context["depth"]) is not int or context["depth"] < 0:
            raise ValueError("插件上下文 depth 必须是非负整数")
        if not isinstance(context["resources"], Mapping) or any(
            not isinstance(key, str) for key in context["resources"]
        ):
            raise ValueError("插件上下文 resources 必须是字符串键对象")
        if schema_version == 2:
            if not isinstance(context.get("intent"), str) or not context["intent"].strip():
                raise ValueError("插件上下文 intent 无效")
            if context.get("operation_support") != "local_commit_v1":
                raise ValueError("插件上下文 operation_support 无效")
            if context.get("fingerprint_scheme") not in {"legacy-v1", "jcs-operation-v1"}:
                raise ValueError("插件上下文 fingerprint_scheme 无效")
        elif "operation_support" in context or "fingerprint_scheme" in context:
            raise ValueError("V1 插件上下文不能包含 operation profile")

        identities = {
            "plugin_id": envelope.get("plugin_id"),
            "plugin_version": envelope.get("plugin_version"),
            "request_id": request.get("request_id"),
            "project_ref": envelope.get("project_ref", request.get("project_ref", "")),
        }
        if any(not isinstance(value, str) or context[key] != value for key, value in identities.items()):
            raise ValueError("插件上下文身份与外层信封不匹配")
        if schema_version == 2 and context["intent"] != request.get("intent"):
            raise ValueError("插件上下文 intent 与请求不匹配")
        outer_digest = envelope.get("provider_digest")
        if outer_digest is not None and outer_digest != context["provider_digest"]:
            raise ValueError("插件上下文身份与外层信封不匹配")

        try:
            canonical_bytes(context)
            immutable = {key: freeze(value) for key, value in context.items()}
        except (TypeError, ValueError, OverflowError):
            raise ValueError("插件上下文包含无效 JSON 数据") from None
        return cls(MappingProxyType(immutable))

    def to_dict(self) -> dict[str, Any]:
        return thaw(self._values)


__all__ = ["PluginContext"]
