from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_ACTOR_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,31}:[a-z][a-z0-9_.-]{0,63}$")
_RESOURCE_PATTERN = re.compile(r"^plugin:[a-z][a-z0-9_.-]{0,63}$")
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_AUDIT_FIELDS = (
    "actor",
    "operation",
    "resource",
    "decision",
    "reason_code",
    "correlation_id",
    "timestamp",
    "result",
    "plugin_id",
    "capability",
    "payload_digest",
)


def canonical_payload_digest(payload: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible payload data.

    The payload is used only to calculate the digest; it is never stored by
    ``AuditRecord`` or ``AuditLogger``.
    """
    canonical = json.dumps(
        _canonical_json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _canonical_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_canonical_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class AuditRecord:
    actor: str
    operation: str
    resource: str
    decision: str
    reason_code: str
    correlation_id: str
    timestamp: str
    result: str
    plugin_id: str
    capability: str
    payload_digest: str

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if not value:
                raise ValueError(f"{field_name} must not be empty")
        if not _ACTOR_PATTERN.fullmatch(self.actor):
            raise ValueError("actor must be a controlled namespaced identifier")
        for field_name in (
            "operation",
            "decision",
            "reason_code",
            "result",
            "plugin_id",
            "capability",
        ):
            if not _IDENTIFIER_PATTERN.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a controlled identifier")
        if not _RESOURCE_PATTERN.fullmatch(self.resource):
            raise ValueError("resource must identify a plugin")
        if not _CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("correlation_id must be a controlled identifier")
        try:
            datetime.fromisoformat(self.timestamp)
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601") from exc
        if not _SHA256_PATTERN.fullmatch(self.payload_digest):
            raise ValueError("payload_digest must be a lowercase SHA-256 hex digest")

    def to_dict(self) -> dict[str, str]:
        return {field_name: getattr(self, field_name) for field_name in _AUDIT_FIELDS}


class AuditLogger:
    """Append metadata-only audit records to a local JSONL file."""

    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "audit.jsonl"

    def write(self, record: AuditRecord) -> None:
        if type(record) is not AuditRecord:
            raise TypeError("record must be an exact AuditRecord")
        serialized = json.dumps(
            record.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
