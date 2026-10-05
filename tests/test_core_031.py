import json
import subprocess

import pytest
import yaml

from test_contract_v3 import make_plugin
from yushuos.manifest import _validate_schema_definition, load_manifest, validate_schema
from yushuos.runtime import CoreRuntime
from yushuos_sdk import Request, Result, StateStore
from yushuos_sdk.canonical import digest
from yushuos_sdk.state import _context_metadata


def test_nullable_schema_accepts_only_null_and_the_declared_value_type():
    schema = {"type": ["string", "null"]}
    _validate_schema_definition(schema, "value")
    assert validate_schema(schema, None) == ""
    assert validate_schema(schema, "text") == ""
    assert "类型无效" in validate_schema(schema, 1)

    null_schema = {"type": "null"}
    _validate_schema_definition(null_schema, "value")
    assert validate_schema(null_schema, None) == ""

    with pytest.raises(ValueError):
        _validate_schema_definition({"type": ["string", "integer", "null"]}, "value")


def test_v1_context_rejects_profile_fields_even_when_null():
    request = Request("legacy-context-1", "task.read", "read")
    legacy = _local_context(request)
    legacy.update(schema_version=1)
    legacy.pop("intent")
    legacy.pop("operation_support")
    legacy.pop("fingerprint_scheme")
    assert _context_metadata(legacy)["schema_version"] == 1

    with pytest.raises(ValueError, match="V1"):
        _context_metadata({**legacy, "operation_support": None})


def test_v3_local_commit_profile_is_explicit_and_rejects_external_writes(tmp_path):
    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    raw = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))
    raw["operation_support"] = "local_commit_v1"
    raw["capabilities"][0]["effect"] = "internal_write"
    raw["capabilities"].append({
        "name": "example.inspect", "effect": "read_only",
        "inputs": {"type": "object"}, "outputs": {"type": "object"},
        "dependencies": [], "permissions": [], "intents": ["read"],
        "implemented": True, "verified": True, "authorized": True, "enabled": True,
        "execution_mode": "standalone",
    })
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    from yushuos.deployment import lock_plugin
    lock_plugin(plugin)
    spec = load_manifest(plugin / "plugin.yaml", verify_lock=False)
    assert spec.operation_support == "local_commit_v1"
    from yushuos.config import load_config
    from yushuos.registry import PluginRegistry
    registry = PluginRegistry([plugin.parent], load_config(plugin.parent))
    catalog_entry = registry.catalog()["plugins"][0]
    assert catalog_entry["operation_support"] == "local_commit_v1"
    write_capability = next(cap for cap in catalog_entry["capabilities"] if cap["effect"] == "internal_write")
    assert write_capability["fingerprint_scheme"] == "jcs-operation-v1"
    assert write_capability["runner_actions"] == ["invoke", "replay", "recover"]

    raw["capabilities"][0]["effect"] = "external_write"
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="operation_support"):
        load_manifest(plugin / "plugin.yaml", verify_lock=False)


def test_operation_fingerprint_is_versioned_without_changing_request_legacy_fingerprint():
    from yushuos_sdk.canonical import fingerprint_for_scheme

    request = Request("fingerprint-1", "task.create", "write", {"title": "x"}, {"store_id": "s1"})
    reordered = Request("fingerprint-1", "task.create", "another-intent", {"title": "x"}, {"store_id": "s1"})
    expected = digest({"capability": "task.create", "fields": {"title": "x"}, "target": {"store_id": "s1"}})

    assert fingerprint_for_scheme(request, "jcs-operation-v1") == expected
    assert fingerprint_for_scheme(reordered, "jcs-operation-v1") == expected
    assert fingerprint_for_scheme(request, "legacy-v1") == request.fingerprint()
    assert request.fingerprint() != fingerprint_for_scheme(request, "jcs-operation-v1")
    with pytest.raises(ValueError, match="scheme"):
        fingerprint_for_scheme(request, "guess-from-hash")


def _local_context(request, *, provider_version="0.1.0", digest_value="a" * 64):
    return {
        "schema_version": 2,
        "plugin_id": "yushuos.task",
        "plugin_version": provider_version,
        "provider_digest": digest_value,
        "project_ref": request.project_ref,
        "request_id": request.request_id,
        "intent": request.intent,
        "state_ledger_path": "/tmp/core/operations.sqlite3",
        "data_path": "/tmp/core/plugin-data/yushuos.task",
        "emitted_events": ["task.created"],
        "run_id": "run-original",
        "root_event_id": "event-root",
        "causation_id": "event-parent",
        "depth": 2,
        "mode": "execute",
        "host_mode": "execute",
        "resources": {},
        "operation_support": "local_commit_v1",
        "fingerprint_scheme": "jcs-operation-v1",
    }


def test_claim_uses_core_bound_fingerprint_profile_and_reconcile_is_immutable(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("task-create-1", "task.create", "write", {"title": "x"}, {"store_id": "store-1"})
    context = _local_context(request)
    store._bind_context(request, context)

    assert store.claim(request)
    with store.connect() as db:
        operation = db.execute("SELECT fingerprint,context_json FROM operation_contexts WHERE request_id=?",
                               (request.request_id,)).fetchone()
    assert operation[0] != request.fingerprint()
    assert json.loads(operation[1])["fingerprint_scheme"] == "jcs-operation-v1"

    result = Result("succeeded", request.request_id, resource={"task_id": "tsk_123"},
                    data={"task": {"title": "PRIVATE"}, "changed": True})
    emissions = [{"type": "task.created", "resource_refs": {"task_id": "tsk_123"}}]
    store.reconcile_confirmed(request, result, context, emissions)

    original = store.receipt(request.request_id)
    effective = store.effective_receipt(request.request_id)
    assert original["receipt"] is None
    assert effective["status"] == "succeeded"
    assert effective["receipt"] == {"status": "succeeded", "request_id": request.request_id}
    assert store.pending_outbox()[0]["envelope"]["root_event_id"] == "event-root"
    assert store.pending_outbox()[0]["envelope"]["source_version"] == "0.1.0"
    assert store.pending_outbox()[0]["envelope"]["provider_digest"] == "a" * 64
    assert b"PRIVATE" not in store.path.read_bytes()

    assert store.reconcile_confirmed(request, result, context, emissions) is False
    with pytest.raises(ValueError, match="event|outbox|核验"):
        store.reconcile_confirmed(request, result, context, [{
            "type": "task.created", "resource_refs": {"task_id": "tsk_different"},
        }])
    with pytest.raises(ValueError, match="succeeded"):
        store.reconcile_confirmed(request, Result("failed", request.request_id), context, [])

    different_intent = Request(request.request_id, request.capability, "different-intent",
                               dict(request.fields), dict(request.target), request.project_ref)
    with pytest.raises(ValueError, match="intent"):
        store.claim(different_intent)


def test_reconcile_confirmation_fails_closed_on_abandoned_or_changed_trace(tmp_path):
    store = StateStore(tmp_path / "operations.sqlite3")
    request = Request("task-create-2", "task.create", "write", {"title": "x"}, {"store_id": "store-1"})
    context = _local_context(request)
    store._bind_context(request, context)
    store.claim(request)
    store.record(Result("unknown", request.request_id))

    with pytest.raises(ValueError, match="trace|binding|bound|绑定"):
        store.reconcile_confirmed(request, Result("succeeded", request.request_id),
                                  {**context, "causation_id": "attacker-trace"}, [])

    store.resolve(request.request_id, "abandoned", actor="operator", reason_code="needs_review")
    with pytest.raises(ValueError, match="Core"):
        store.reconcile_confirmed(request, Result("succeeded", request.request_id), context, [])


def test_preview_internal_write_does_not_create_plugin_data_path(tmp_path):
    from yushuos.deployment import lock_plugin

    plugin = make_plugin(tmp_path / "plugins", contract_version=3)
    raw = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))
    raw["operation_support"] = "local_commit_v1"
    raw["capabilities"][0]["effect"] = "internal_write"
    raw["capabilities"][0]["execution_mode"] = "standalone"
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)

    runtime = CoreRuntime(tmp_path / "config")
    ledger = tmp_path / "config" / "operations.sqlite3"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    StateStore(ledger).claim(Request("seed", "seed.capability", "write"))
    runtime.state = StateStore(ledger)
    runtime.config["_ledger_path"] = str(ledger)
    from yushuos.manifest import load_manifest
    from yushuos.registry import CapabilityBinding
    spec = load_manifest(plugin / "plugin.yaml")
    binding = CapabilityBinding(spec, spec.capabilities[0], True, ())
    runtime.config["execution"]["preview_business_writes"] = True
    captured = []

    def invoke(args, **kwargs):
        envelope = json.loads(kwargs["input"])
        captured.append(envelope)
        return subprocess.CompletedProcess(args, 0, json.dumps({"status": "preview", "request_id": envelope["request"]["request_id"],
            "message": "preview", "resource": {}, "data": {"planned": True}, "error": None}), "")

    runtime.runner.run = invoke
    request = Request("preview-no-write", "example.echo", "read", {"message": "x"})
    result = runtime.runner.invoke(binding, request, mode="preview", host_mode="execute")
    assert result.status == "preview"
    from yushuos_sdk.context import PluginContext
    context = PluginContext.from_envelope(captured[0])
    assert context.schema_version == 2
    assert context.intent == "read"
    assert not (tmp_path / "config" / "plugin-data").exists()
    assert ledger.exists()
    assert runtime.state.operation_context(request.request_id) is None


def test_core_local_commit_preview_returns_validated_plan_without_dispatch_or_storage(tmp_path):
    from types import SimpleNamespace

    from yushuos.deployment import lock_plugin
    from yushuos.manifest import load_manifest
    from yushuos.registry import CapabilityBinding

    root = tmp_path / "core"
    plugin = make_plugin(root / "plugins", contract_version=3)
    raw = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))
    raw["operation_support"] = "local_commit_v1"
    raw["capabilities"][0].update({"effect": "internal_write", "intents": ["write"]})
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)
    spec = load_manifest(plugin / "plugin.yaml")
    binding = CapabilityBinding(spec, spec.capabilities[0], True, ())
    runtime = CoreRuntime(root)
    runtime.registry = SimpleNamespace(resolve=lambda capability: binding,
                                       unavailable_reasons=lambda capability: [])
    runtime.runner.run = lambda *args, **kwargs: pytest.fail("preview must not start the plugin runner")

    result = runtime.invoke({"request_id": "preview-plan", "capability": "example.echo", "intent": "write",
                             "fields": {"message": "preview body"}, "target": {"store_id": "store-1"}},
                            mode="preview", host_mode="readonly")
    assert result.status == "preview"
    assert result.data == {
        "capability": "example.echo", "planned_fields": {"message": "preview body"},
        "target": {"store_id": "store-1"}, "write_performed": False,
    }
    assert not (root / "plugin-data").exists()
    assert not (root / "state" / "operations.sqlite3").exists()


def test_explicit_resume_recovers_and_terminal_duplicate_replays_with_original_binding(tmp_path):
    from types import SimpleNamespace

    from yushuos.deployment import lock_plugin
    from yushuos.manifest import load_manifest
    from yushuos.registry import CapabilityBinding
    from yushuos_sdk.context import PluginContext

    root = tmp_path / "core"
    plugin = make_plugin(root / "plugins", contract_version=3)
    raw = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))
    raw["operation_support"] = "local_commit_v1"
    raw["emitted_events"] = ["example.echo.completed"]
    raw["capabilities"][0].update({"effect": "internal_write", "intents": ["write"], "verified": True,
                                    "authorized": True, "enabled": True})
    (plugin / "plugin.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    lock_plugin(plugin)
    spec = load_manifest(plugin / "plugin.yaml")
    binding = CapabilityBinding(spec, spec.capabilities[0], True, ())

    ledger = root / "state" / "operations.sqlite3"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    store = StateStore(ledger)
    with store.connect(write=True):
        pass
    runtime = CoreRuntime(root)
    runtime.state = store
    runtime.config["_ledger_path"] = str(ledger)
    runtime.config["permissions"]["grants"] = ["example.echo"]
    runtime.config["execution"]["preview_business_writes"] = True
    runtime.registry = SimpleNamespace(resolve=lambda capability: binding if capability == spec.capabilities[0].name else None,
                                       unavailable_reasons=lambda capability: [])
    actions = []
    saved_result = None

    def invoke(args, **kwargs):
        nonlocal saved_result
        envelope = json.loads(kwargs["input"])
        action = envelope["action"]
        actions.append(action)
        request = Request(**envelope["request"])
        state = StateStore(envelope["context"]["state_ledger_path"])
        if action == "invoke":
            assert state.claim(request)
            result = Result("unknown", request.request_id)
            state.record(result)
        elif action == "recover":
            context = PluginContext.from_envelope(envelope)
            saved_result = Result("succeeded", request.request_id, resource={"task_id": "tsk_1"},
                                  data={"task": {"title": "saved"}, "changed": True})
            state.reconcile_confirmed(request, saved_result, context, [{
                "type": "example.echo.completed", "resource_refs": {"task_id": "tsk_1"},
            }])
            result = saved_result
        else:
            result = saved_result
        return subprocess.CompletedProcess(args, 0, json.dumps(result.to_dict()), "")

    runtime.runner.run = invoke
    request = {"request_id": "local-recover-1", "capability": "example.echo", "intent": "write",
               "fields": {"message": "business input"}}
    assert runtime.invoke(request, mode="execute", host_mode="execute").status == "unknown"
    assert runtime.invoke(request, mode="execute", host_mode="execute").status == "unknown"
    assert actions == ["invoke"]

    recovered = runtime.resume(request, host_mode="execute")
    assert recovered.status == "succeeded"
    assert actions == ["invoke", "recover"]
    context = store.operation_context("local-recover-1")
    assert context["fingerprint_scheme"] == "jcs-operation-v1"
    assert context["intent"] == "write"
    assert context["run_id"] == ""
    assert store.effective_receipt("local-recover-1")["confirmation"]

    replayed = runtime.invoke(request, mode="execute", host_mode="execute")
    assert replayed.data == {"task": {"title": "saved"}, "changed": True}
    assert actions == ["invoke", "recover", "replay"]

    with (plugin / "run.py").open("a", encoding="utf-8") as file:
        file.write("\n# provider drift\n")
    assert runtime.invoke(request, mode="execute", host_mode="execute").status == "unavailable"
    assert actions == ["invoke", "recover", "replay"]


def test_status_provenance_gracefully_handles_legacy_ledger_without_v3_tables(tmp_path):
    import sqlite3

    ledger = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE operations (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, resource_key TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT, updated TEXT NOT NULL)")
        db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?)", ("old-1", "f" * 64, "request:old-1", "succeeded", None, "now"))

    store = StateStore(ledger)
    status = store.status_with_provenance("old-1")
    assert status == store.receipt("old-1")
    assert "provenance" not in status
