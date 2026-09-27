from pathlib import Path

import pytest

from agents.information_pipeline import InformationPipeline
from capability_plugins.loader import load_manifests
from information_system import InformationStore


MANIFEST_DIR = Path(__file__).parents[2] / "capability_plugins" / "manifests"
EXPECTED_CAPABILITIES = {
    "information.capture",
    "information.recognize",
    "information.get",
    "information.list_inbox",
    "information.propose_domain",
}


def _api():
    from capability_plugins.information import InformationPlugin, InformationPluginError

    return InformationPlugin, InformationPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "information"
    )


class _Outcome:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _Report(_Outcome):
    pass


class _Recognizer:
    def __init__(self):
        self.calls = []

    def recognize(self, obj, text, **kwargs):
        self.calls.append((obj, text, kwargs))
        return _Report({"recognition": {"object_id": kwargs.get("object_id", "")}})


class _Observer:
    def __init__(self):
        self.calls = []

    def suggested_promotions(self, *, min_evidence):
        self.calls.append(min_evidence)
        return [{"label": "候选领域", "action": "await_human_confirmation"}]


class _Store:
    def __init__(self):
        self.calls = []

    def get(self, object_id):
        self.calls.append(("get", object_id))
        return {"object_id": object_id, "title": "条目"}

    def list_objects(self, **kwargs):
        self.calls.append(("list_objects", kwargs))
        return [{"object_id": "obj-1", "status": kwargs.get("status")}]


class _Ingestion:
    def __init__(self):
        self.recognizer = _Recognizer()
        self.observer = _Observer()


class _Pipeline:
    def __init__(self):
        self.store = _Store()
        self.ingestion = _Ingestion()
        self.ingest_calls = []

    def ingest(self, **kwargs):
        self.ingest_calls.append(kwargs)
        return _Outcome({"object_id": "obj-1", "created": True, **kwargs})


def test_information_manifest_declares_wp4_capabilities_and_no_external_write():
    manifest = _manifest()

    assert set(manifest.provides) == EXPECTED_CAPABILITIES
    assert "information.sqlite" in manifest.writes
    assert not any(item.startswith("external.") for item in manifest.writes)


def test_information_plugin_maps_all_capabilities_to_existing_pipeline_services():
    InformationPlugin, _ = _api()
    pipeline = _Pipeline()
    plugin = InformationPlugin(_manifest(), pipeline)
    marker = object()

    captured = plugin.invoke(
        "information.capture",
        {"source": "manual", "title": "记录", "content": "正文"},
        {},
    )
    recognized = plugin.invoke(
        "information.recognize",
        {"object": marker, "text": "正文", "object_id": "obj-1"},
        {},
    )
    loaded = plugin.invoke("information.get", {"object_id": "obj-1"}, {})
    inbox = plugin.invoke("information.list_inbox", {"limit": 20}, {})
    proposals = plugin.invoke(
        "information.propose_domain", {"min_evidence": 3}, {}
    )

    assert captured["object_id"] == "obj-1"
    assert pipeline.ingest_calls == [
        {"source": "manual", "title": "记录", "content": "正文"}
    ]
    assert recognized == {"recognition": {"object_id": "obj-1"}}
    assert pipeline.ingestion.recognizer.calls == [
        (marker, "正文", {"object_id": "obj-1"})
    ]
    assert loaded["object_id"] == "obj-1"
    assert inbox == [{"object_id": "obj-1", "status": "inbox"}]
    assert pipeline.store.calls[-1] == (
        "list_objects",
        {"status": "inbox", "limit": 20},
    )
    assert proposals[0]["action"] == "await_human_confirmation"
    assert pipeline.ingestion.observer.calls == [3]


def test_information_plugin_real_capture_matches_existing_pipeline_core_fields(tmp_path):
    InformationPlugin, _ = _api()
    direct_store = InformationStore(tmp_path / "direct.db")
    plugin_store = InformationStore(tmp_path / "plugin.db")
    direct_store.init_schema()
    plugin_store.init_schema()
    direct_pipeline = InformationPipeline(direct_store)
    plugin_pipeline = InformationPipeline(plugin_store)
    payload = {
        "source": "manual",
        "title": "睡眠记录",
        "content": "昨晚睡眠七小时，今天需要降低训练强度。",
        "correlation_id": "corr-information-plugin",
    }

    direct = direct_pipeline.ingest(**payload).to_dict()
    adapted = InformationPlugin(_manifest(), plugin_pipeline).invoke(
        "information.capture", payload, {}
    )

    for field in (
        "created",
        "source",
        "recommendation",
        "knowledge_level",
        "cognitive_os_level",
        "domains",
        "topic_label",
        "topic_state",
    ):
        assert adapted[field] == direct[field]
    assert plugin_store.get(adapted["object_id"])["status"] == "inbox"


def test_information_plugin_maps_legacy_exception_without_leaking_body():
    InformationPlugin, InformationPluginError = _api()
    pipeline = _Pipeline()

    def fail(**kwargs):
        raise RuntimeError("SENSITIVE-INFORMATION-BODY")

    pipeline.ingest = fail
    plugin = InformationPlugin(_manifest(), pipeline)

    with pytest.raises(InformationPluginError) as exc_info:
        plugin.invoke(
            "information.capture",
            {"source": "manual", "title": "记录", "content": "正文"},
            {},
        )

    assert exc_info.value.error_code == "information_backend_failed"
    assert "SENSITIVE-INFORMATION-BODY" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_information_plugin_rejects_unknown_capability_without_touching_pipeline():
    InformationPlugin, InformationPluginError = _api()
    pipeline = _Pipeline()
    plugin = InformationPlugin(_manifest(), pipeline)

    with pytest.raises(InformationPluginError) as exc_info:
        plugin.invoke("information.delete", {}, {})

    assert exc_info.value.error_code == "unsupported_capability"
    assert pipeline.ingest_calls == []


def test_disabling_information_plugin_does_not_change_existing_pipeline(tmp_path):
    store = InformationStore(tmp_path / "legacy.db")
    store.init_schema()
    pipeline = InformationPipeline(store)

    outcome = pipeline.ingest(
        source="manual",
        title="旧入口仍可用",
        content="关闭插件不应影响已有 InformationPipeline。",
    )

    assert store.get(outcome.object_id)["title"] == "旧入口仍可用"
