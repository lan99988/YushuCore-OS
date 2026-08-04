"""Validation for frozen Personal Knowledge OS v3.0 metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from knowledge_system.schema.definitions import (
    ALLOWED_KNOWLEDGE_TYPES,
    ALLOWED_SENSITIVITY_LEVELS,
    ALLOWED_STATUSES,
    KNOWN_METADATA_FIELDS,
    REQUIRED_METADATA_FIELDS,
)


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    code: str


@dataclass(frozen=True)
class ValidationResult:
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]

    @property
    def valid(self) -> bool:
        return not self.errors


def _is_iso_date(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_string_list(value: Any, *, allow_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def validate_metadata(metadata: dict[str, Any]) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    for field in sorted(REQUIRED_METADATA_FIELDS - metadata.keys()):
        errors.append(ValidationIssue(field, "required field is missing", "required"))

    if "id" in metadata and not (
        isinstance(metadata["id"], str) and metadata["id"].strip()
    ):
        errors.append(ValidationIssue("id", "must be a non-empty string", "type"))

    if "type" in metadata and metadata["type"] not in ALLOWED_KNOWLEDGE_TYPES:
        errors.append(ValidationIssue("type", "is not an allowed knowledge type", "enum"))

    if "status" in metadata and metadata["status"] not in ALLOWED_STATUSES:
        errors.append(ValidationIssue("status", "is not a lifecycle status", "enum"))

    if "domain" in metadata and not _is_string_list(metadata["domain"], allow_empty=False):
        errors.append(ValidationIssue("domain", "must be a non-empty string list", "type"))

    if "source" in metadata and not _is_string_list(metadata["source"], allow_empty=True):
        errors.append(ValidationIssue("source", "must be a string list", "type"))

    if "agent_access" in metadata and not _is_string_list(
        metadata["agent_access"], allow_empty=True
    ):
        errors.append(ValidationIssue("agent_access", "must be a string list", "type"))

    if "confidence" in metadata:
        confidence = metadata["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            errors.append(ValidationIssue("confidence", "must be a number", "type"))
        elif not 0.0 <= float(confidence) <= 1.0:
            errors.append(ValidationIssue("confidence", "must be between 0 and 1", "range"))

    for field in ("created", "updated"):
        if field in metadata and not _is_iso_date(metadata[field]):
            errors.append(ValidationIssue(field, "must be an ISO date", "format"))

    if "layer" in metadata:
        layer = metadata["layer"]
        valid_layer = (
            isinstance(layer, int)
            and not isinstance(layer, bool)
            and 0 <= layer <= 4
        ) or layer in {"raw", "knowledge", "cognition", "agent_intelligence", "self_model"}
        if not valid_layer:
            errors.append(ValidationIssue("layer", "must identify cognitive layer 0-4", "enum"))

    if "sensitivity" in metadata and metadata["sensitivity"] not in ALLOWED_SENSITIVITY_LEVELS:
        errors.append(ValidationIssue("sensitivity", "must be level_0 through level_4", "enum"))

    for field in sorted(metadata.keys() - KNOWN_METADATA_FIELDS):
        warnings.append(ValidationIssue(field, "unknown field was preserved", "unknown"))

    return ValidationResult(errors=errors, warnings=warnings)
