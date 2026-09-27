from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import re
from typing import Any

from runtime_core.audit import canonical_payload_digest


EventHandler = Callable[[dict[str, Any]], None]

_SENSITIVE_EXACT_KEYS = {
    "task",
    "payload",
    "content",
    "message",
    "body",
    "text",
    "prompt",
    "old",
    "new",
    "credential",
    "secret",
    "financial_screenshot",
    "health_raw_data",
    "password",
    "token",
    "api_key",
    "authorization",
    "query",
    "title",
    "result",
    "exception",
    "reason",
    "financial_screenshot_body",
    "external_message_body",
}
_SENSITIVE_PREFIXES = (
    "credential",
    "secret",
    "password",
    "token",
    "payload",
    "content",
    "message",
    "body",
    "text",
    "prompt",
    "financialscreenshot",
    "healthrawdata",
    "query",
    "title",
    "result",
    "exception",
    "reason",
)
_SENSITIVE_SUFFIXES = (
    "credential",
    "secret",
    "password",
    "token",
    "payload",
    "content",
    "message",
    "body",
    "text",
    "prompt",
)


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    if normalized.endswith(("digest", "hash")):
        return False
    exact = {_normalized_key(item) for item in _SENSITIVE_EXACT_KEYS}
    if normalized in exact:
        return True
    if normalized.startswith(("old", "new")) and len(normalized) > 3:
        return True
    return normalized.startswith(_SENSITIVE_PREFIXES) or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redacted_summary(value: Any) -> dict[str, Any]:
    if (
        isinstance(value, dict)
        and value.get("redacted") is True
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and all(char in "0123456789abcdef" for char in value["sha256"])
    ):
        return deepcopy(value)
    try:
        digest = canonical_payload_digest(value)
    except (TypeError, ValueError):
        return {"redacted": True}
    return {"redacted": True, "sha256": digest}


_WP9_EVENT_FIELDS = {
    "flow_started": frozenset({"event", "timestamp", "correlation_id", "flow"}),
    "flow_completed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "status"}
    ),
    "flow_failed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "error_type", "error_code"}
    ),
    "plan_created": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "step_count"}
    ),
    "policy_allowed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "agent_id", "plugin_id", "capability", "step_id", "reason_code"}
    ),
    "policy_blocked": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "agent_id", "plugin_id", "capability", "step_id", "reason_code"}
    ),
    "approval_required": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "agent_id", "plugin_id", "capability", "step_id", "reason_code"}
    ),
    "plugin_started": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "plugin_id", "capability", "step_id"}
    ),
    "plugin_completed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "plugin_id", "capability", "step_id", "status"}
    ),
    "plugin_failed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "plugin_id", "capability", "step_id", "error_type", "error_code"}
    ),
    "partial_result": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "source", "status", "step_count", "completed_count", "failed_count", "blocked_count"}
    ),
    "rollback_started": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "plugin_id", "capability", "step_id", "rollback_count"}
    ),
    "rollback_completed": frozenset(
        {"event", "timestamp", "correlation_id", "flow", "plugin_id", "capability", "step_id", "rollback_count", "status"}
    ),
}
_CONTROLLED_META = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")
_FLOW_VALUES = {"capture", "plan", "today", "adjust", "review", "explore", "unresolved"}
_SAFE_LEGACY_REASON_CODES = {
    "use_tools_denied",
    "unknown_tool",
    "access_request_not_approved",
    "access_request_already_used",
    "unknown_target",
    "invalid_change",
    "separation_of_duties",
    "local_first",
    "sensitive_context_requires_local_model",
    "complex_task_with_network_enabled",
}


def _safe_wp9_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event.get("event")
    allowed = _WP9_EVENT_FIELDS.get(event_type) if isinstance(event_type, str) else None
    if allowed is None:
        return {}
    safe: dict[str, Any] = {"event": event_type}
    for key in allowed - {"event"}:
        value = event.get(key)
        if key == "flow":
            if value in _FLOW_VALUES:
                safe[key] = value
        elif key.endswith("_count") or key in {"step_count", "completed_count", "failed_count", "blocked_count", "rollback_count"}:
            if type(value) is int and value >= 0:
                safe[key] = value
        elif key == "status":
            if isinstance(value, str) and _CONTROLLED_META.fullmatch(value):
                safe[key] = value
        elif key == "source":
            if value in {"flow", "executor"}:
                safe[key] = value
        elif key == "timestamp":
            if isinstance(value, str) and len(value) <= 64:
                safe[key] = value
        elif key in {"correlation_id", "agent_id", "plugin_id", "capability", "step_id", "reason_code", "error_type", "error_code"}:
            if isinstance(value, str) and _CONTROLLED_META.fullmatch(value):
                safe[key] = value
    return safe


def _safe_value(value: Any, *, event_type: str = "") -> Any:
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            if key == "reason":
                controlled_reasons = (
                    _SAFE_LEGACY_REASON_CODES
                    if event_type == "model_route_selected"
                    else _SAFE_LEGACY_REASON_CODES - {"local_first", "sensitive_context_requires_local_model", "complex_task_with_network_enabled"}
                )
                if isinstance(item, str) and item in controlled_reasons:
                    safe[str(key)] = item
                else:
                    safe[str(key)] = _redacted_summary(item)
            elif _is_sensitive_key(key):
                safe[str(key)] = _redacted_summary(item)
            else:
                safe[str(key)] = _safe_value(item, event_type=event_type)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, event_type=event_type) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _redacted_summary(value)


def safe_event_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    """Build a detached event snapshot with allowlisted WP9 metadata."""
    event_type = event.get("event")
    if isinstance(event_type, str) and event_type in _WP9_EVENT_FIELDS:
        return _safe_wp9_event(event)
    return _safe_value(event, event_type=event_type if isinstance(event_type, str) else "")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []
        self._history: list[dict[str, Any]] = []

    @property
    def history(self) -> list[dict[str, Any]]:
        return deepcopy(self._history)

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def publish(self, event: dict[str, Any]) -> None:
        safe_event = safe_event_snapshot(event)
        self._history.append(deepcopy(safe_event))
        for handler in self._subscribers:
            try:
                handler(deepcopy(safe_event))
            except Exception:
                # Telemetry consumers must not change the operation being observed.
                continue
