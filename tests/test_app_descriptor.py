from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _api():
    try:
        module = importlib.import_module("yushuos.app_descriptor")
    except ImportError:
        pytest.fail("required module is missing: yushuos.app_descriptor")
    assert callable(getattr(module, "validate_app_descriptor", None)), "validate_app_descriptor API is missing"
    assert callable(getattr(module, "load_app_descriptor", None)), "load_app_descriptor API is missing"
    return module


def valid_descriptor() -> dict:
    return {
        "schema_version": 1,
        "app": "ima",
        "version": "1.2.3",
        "capabilities": [
            {
                "id": "ima.calendar.create",
                "description": "Create a calendar event.",
                "effect": "external_write",
                "intent": "schedule",
                "input_schema": {
                    "type": "object",
                    "required": ["title", "calendar_id"],
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string", "minLength": 1},
                        "calendar_id": {"type": "string"},
                    },
                },
                "output_schema": {"type": "object", "properties": {"event_id": {"type": "string"}}},
                "execution_mode": "host_required",
                "auth": {"required": True, "scopes": ["calendar.write"]},
                "resource_bindings": {"calendar_id": "primary_calendar"},
            }
        ],
    }


def test_descriptor_returns_normalized_explicit_contract():
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"].append({
        "id": "ima.calendar.list",
        "effect": "read_only",
        "intent": "query",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "execution_mode": "standalone",
        "auth": {"required": False, "scopes": []},
        "resource_bindings": {},
    })

    normalized = module.validate_app_descriptor(raw)
    assert normalized["schema_version"] == 1
    assert normalized["app"] == "ima"
    assert [capability["id"] for capability in normalized["capabilities"]] == [
        "ima.calendar.create", "ima.calendar.list"
    ]
    assert normalized["capabilities"][0]["resource_bindings"] == {"calendar_id": "primary_calendar"}
    assert normalized["capabilities"][0]["auth"] == {"required": True, "scopes": ["calendar.write"]}


@pytest.mark.parametrize(
    "field",
    ["effect", "intent", "input_schema", "output_schema", "execution_mode", "auth", "resource_bindings"],
)
def test_descriptor_requires_every_policy_and_schema_field(field):
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0].pop(field)
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)


def test_descriptor_rejects_unknown_fields_at_each_level():
    module = _api()
    raw = valid_descriptor()
    raw["credentials"] = {"access_token": "do-not-accept"}
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)

    raw = valid_descriptor()
    raw["capabilities"][0]["policy_override"] = True
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)

    raw = valid_descriptor()
    raw["capabilities"][0]["auth"]["access_token"] = "do-not-accept"
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)


@pytest.mark.parametrize("effect", ["", "write", "admin", "external_write|read_only"])
def test_descriptor_rejects_effect_outside_supported_set(effect):
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0]["effect"] = effect
    with pytest.raises(ValueError, match="effect"):
        module.validate_app_descriptor(raw)


@pytest.mark.parametrize("execution_mode", ["", "either", "host", "standalone|host_required"])
def test_descriptor_rejects_invalid_execution_mode(execution_mode):
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0]["execution_mode"] = execution_mode
    with pytest.raises(ValueError, match="execution_mode"):
        module.validate_app_descriptor(raw)


@pytest.mark.parametrize("bad_scope", ["", " ", "../secret", "calendar/read"])
def test_descriptor_rejects_invalid_or_path_like_resource_bindings(bad_scope):
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0]["resource_bindings"]["calendar_id"] = bad_scope
    with pytest.raises(ValueError, match="resource_bindings"):
        module.validate_app_descriptor(raw)


def test_descriptor_resource_binding_must_reference_an_input_field():
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0]["resource_bindings"] = {"unknown_field": "primary_calendar"}
    with pytest.raises(ValueError, match="resource_bindings"):
        module.validate_app_descriptor(raw)


def test_descriptor_rejects_credentials_nested_in_any_field_without_echoing_them():
    module = _api()
    token = "private-access-token-value"
    raw = valid_descriptor()
    raw["capabilities"][0]["input_schema"]["properties"]["access_token"] = {"type": "string"}
    with pytest.raises(ValueError) as caught:
        module.validate_app_descriptor(raw)
    assert token not in str(caught.value)

    raw = valid_descriptor()
    raw["capabilities"][0]["description"] = f"Authorization: Bearer {token}"
    with pytest.raises(ValueError) as caught:
        module.validate_app_descriptor(raw)
    assert token not in str(caught.value)


def test_descriptor_schema_version_identity_and_capability_ids_are_strict():
    module = _api()
    raw = valid_descriptor()
    raw["schema_version"] = True
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)

    raw = valid_descriptor()
    raw["capabilities"].append(raw["capabilities"][0].copy())
    with pytest.raises(ValueError, match="重复"):
        module.validate_app_descriptor(raw)

    raw = valid_descriptor()
    raw["capabilities"][0]["id"] = "../outside"
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)


def test_descriptor_auth_and_schema_values_are_validated():
    module = _api()
    raw = valid_descriptor()
    raw["capabilities"][0]["auth"]["required"] = 1
    with pytest.raises(ValueError, match="auth"):
        module.validate_app_descriptor(raw)

    raw = valid_descriptor()
    raw["capabilities"][0]["input_schema"]["properties"]["title"]["unsupported"] = True
    with pytest.raises(ValueError):
        module.validate_app_descriptor(raw)


def test_descriptor_loader_uses_strict_json_and_returns_normalized_data(tmp_path):
    module = _api()
    descriptor_path = tmp_path / "app-descriptor.json"
    descriptor_path.write_text(json.dumps(valid_descriptor()), encoding="utf-8")
    loaded = module.load_app_descriptor(descriptor_path)
    assert loaded == module.validate_app_descriptor(valid_descriptor())

    descriptor_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError):
        module.load_app_descriptor(descriptor_path)


def test_descriptor_loader_rejects_linked_paths(tmp_path, monkeypatch):
    module = _api()
    linked = tmp_path / "linked.json"
    linked.write_text(json.dumps(valid_descriptor()), encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def report_link(path: Path) -> bool:
        return path == linked or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_link)
    with pytest.raises(ValueError, match="链接"):
        module.load_app_descriptor(linked)


def test_old_ima_feishu_static_capability_list_is_not_misread_as_descriptor():
    module = _api()
    legacy = [{"id": "ima.kb.search", "implemented": True}]
    with pytest.raises(ValueError):
        module.validate_app_descriptor(legacy)
