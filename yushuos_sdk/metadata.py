"""Privacy filters for durable SDK metadata."""

from collections.abc import Mapping
import math
from urllib.parse import urlsplit, urlunsplit
from typing import Any


# Only stable identifiers and references belong in receipts and event envelopes.
_RESOURCE_REF_KEYS = frozenset({
    "id", "type", "ref", "uri", "url", "hash", "etag", "project_ref",
    "resource_id", "resource_type", "request_id", "plugin_id",
    "calendar_id", "event_id", "task_id", "task_guid", "base_id",
    "table_id", "record_id", "document_id", "doc_id", "file_id",
    "folder_id", "drive_id", "thread_id", "message_id", "meeting_id",
    "minute_id", "wiki_id", "node_id", "approval_id", "instance_id",
})


def _safe_scalar(value: Any, key: str) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 512 or any(ord(char) < 32 for char in value):
        return None
    if "://" in value or key in {"url", "uri"}:
        # Keep the location while dropping userinfo, query strings, and fragments
        # that can carry credentials or user supplied text.
        try:
            parts = urlsplit(value)
            if parts.scheme.lower() in {"http", "https"} and parts.netloc:
                hostname = parts.hostname
                if not hostname:
                    return None
                if ":" in hostname and not hostname.startswith("["):
                    hostname = f"[{hostname}]"
                authority = hostname + (f":{parts.port}" if parts.port is not None else "")
                return urlunsplit((parts.scheme.lower(), authority, parts.path, "", ""))
            if key in {"url", "uri"}:
                return None
            if parts.scheme and parts.path:
                return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            return None
    return value


def safe_resource_refs(resource: Any) -> dict[str, str | int | float | bool | None]:
    """Return only short, allow-listed resource identifiers from a provider value.

    Free-form fields such as message, error, data, title, and arbitrary nested
    objects are discarded. The function intentionally accepts provider mappings
    without requiring them to use one provider's naming convention.
    """
    if not isinstance(resource, Mapping):
        return {}
    refs: dict[str, str | int | float | bool | None] = {}
    for key, value in resource.items():
        if not isinstance(key, str) or key.lower() not in _RESOURCE_REF_KEYS:
            continue
        normalized_key = key.lower()
        safe_value = _safe_scalar(value, normalized_key)
        if safe_value is not None:
            refs[normalized_key] = safe_value
    return dict(sorted(refs.items()))


__all__ = ["safe_resource_refs"]
