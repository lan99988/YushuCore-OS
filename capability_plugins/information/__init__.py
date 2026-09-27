"""Thin capability adapter for the existing information pipeline."""

from __future__ import annotations

from typing import Any

from capability_plugins.contracts import PluginManifest


_CAPABILITIES = frozenset(
    {
        "information.capture",
        "information.recognize",
        "information.get",
        "information.list_inbox",
        "information.propose_domain",
    }
)


class InformationPluginError(RuntimeError):
    """Controlled adapter error that never includes source body text."""

    def __init__(self, error_code: str, *, cause_type: str = "") -> None:
        self.error_code = error_code
        self.cause_type = cause_type
        super().__init__(error_code)


class InformationPlugin:
    """Map information capabilities to the existing pipeline without reimplementation."""

    def __init__(self, manifest: PluginManifest, pipeline: Any) -> None:
        if not isinstance(manifest, PluginManifest):
            raise TypeError("manifest must be a PluginManifest")
        if manifest.plugin_id != "information":
            raise ValueError("information plugin requires the information manifest")
        missing = _CAPABILITIES - set(manifest.provides)
        if missing:
            raise ValueError(
                "information manifest is missing capabilities: "
                + ", ".join(sorted(missing))
            )
        if not callable(getattr(pipeline, "ingest", None)):
            raise TypeError("pipeline must provide ingest")
        if getattr(pipeline, "store", None) is None:
            raise TypeError("pipeline must expose its information store")
        if getattr(pipeline, "ingestion", None) is None:
            raise TypeError("pipeline must expose its ingestion services")
        self.manifest = manifest
        self._pipeline = pipeline

    def invoke(
        self, capability: str, payload: dict[str, Any], context: Any
    ) -> Any:
        if capability not in _CAPABILITIES or capability not in self.manifest.provides:
            raise InformationPluginError("unsupported_capability")
        if not isinstance(payload, dict):
            raise InformationPluginError("invalid_payload")
        try:
            if capability == "information.capture":
                return _view(self._pipeline.ingest(**_capture_arguments(payload)))
            if capability == "information.recognize":
                recognizer = self._pipeline.ingestion.recognizer
                obj = payload["object"]
                text = payload["text"]
                kwargs = {
                    key: payload[key]
                    for key in ("known_domains", "object_id", "moment")
                    if key in payload
                }
                return _view(recognizer.recognize(obj, text, **kwargs))
            if capability == "information.get":
                return _view(self._pipeline.store.get(str(payload["object_id"])))
            if capability == "information.list_inbox":
                limit = _positive_limit(payload.get("limit", 100))
                return _view(
                    self._pipeline.store.list_objects(status="inbox", limit=limit)
                )
            observer = self._pipeline.ingestion.observer
            if observer is None:
                raise InformationPluginError("information_observer_unavailable")
            min_evidence = _positive_limit(payload.get("min_evidence", 3))
            return _view(observer.suggested_promotions(min_evidence=min_evidence))
        except InformationPluginError:
            raise
        except Exception as exc:
            raise InformationPluginError(
                "information_backend_failed", cause_type=type(exc).__name__
            ) from None


def _capture_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("source", "title", "content")
    if any(key not in payload for key in required):
        raise InformationPluginError("invalid_payload")
    allowed = (
        "source",
        "title",
        "content",
        "source_ref",
        "source_container",
        "correlation_id",
        "moment",
    )
    return {key: payload[key] for key in allowed if key in payload}


def _positive_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InformationPluginError("invalid_payload")
    return value


def _view(value: Any) -> Any:
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        return serializer()
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return [_view(item) for item in value]
    return value


__all__ = ["InformationPlugin", "InformationPluginError"]
