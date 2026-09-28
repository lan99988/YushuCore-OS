from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from capability_plugins.manifest import manifest_from_dict
from yushu_app.store import LocalStore, RecordConflict


class LocalRecordPluginError(ValueError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class LocalRecordPlugin:
    """Governed local persistence for profile-owned domain records."""

    def __init__(self, store: LocalStore) -> None:
        if not isinstance(store, LocalStore):
            raise TypeError("store must be a LocalStore")
        manifest_path = Path(__file__).resolve().parents[1] / "manifests" / "local_record.yaml"
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.manifest = manifest_from_dict(payload)
        self._store = store

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        if capability not in self.manifest.provides:
            raise LocalRecordPluginError("unsupported_capability")
        if type(payload) is not dict or not isinstance(context, dict):
            raise LocalRecordPluginError("invalid_payload")
        kind = payload.get("kind")
        if not isinstance(kind, str):
            raise LocalRecordPluginError("invalid_payload")
        if kind in {"task", "calendar"} and self._store.profile.authority(kind) != "local":
            raise LocalRecordPluginError("source_not_local")

        try:
            if capability == "local_record.list":
                return {"records": self._store.list(kind), "source": "local"}
            if capability == "local_record.get":
                record_id = payload.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise ValueError("record_id is required")
                record = self._store.get(kind, record_id)
                if record is None:
                    raise LocalRecordPluginError("record_not_found")
                return {"record": record, "source": "local"}

            actor = context.get("agent_id")
            correlation_id = context.get("correlation_id")
            if not isinstance(actor, str) or not isinstance(correlation_id, str):
                raise ValueError("runtime identity is missing")
            if capability == "local_record.create":
                record = self._store.create(
                    kind,
                    payload.get("data"),
                    actor=f"agent:{actor}",
                    correlation_id=correlation_id,
                    idempotency_key=payload.get("idempotency_key"),
                )
            else:
                record = self._store.update(
                    kind,
                    payload.get("record_id"),
                    payload.get("data"),
                    expected_version=payload.get("expected_version"),
                    actor=f"agent:{actor}",
                    correlation_id=correlation_id,
                )
            return {"record": record, "source": "local"}
        except LocalRecordPluginError:
            raise
        except RecordConflict:
            raise LocalRecordPluginError("record_conflict") from None
        except (TypeError, ValueError):
            raise LocalRecordPluginError("invalid_payload") from None
