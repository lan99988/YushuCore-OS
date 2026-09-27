from __future__ import annotations

import ast
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, Availability, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
SCHEMA_PATH = (
    ROOT
    / "04_数据中心（Data）"
    / "数据模型（Schema）"
    / "04_个人领域"
    / "LifeAdminItem.json"
)
EXPECTED_CATEGORIES = (
    "identity_documents",
    "home_facilities",
    "personal_asset_maintenance",
    "services_contracts",
    "administrative_procedures",
)
EXPECTED_CAPABILITIES = (
    "life_admin.domains",
    "life_admin.capture",
)


def _api():
    try:
        spec = importlib.util.find_spec("capability_plugins.life_admin.plugin")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "capability_plugins.life_admin.plugin is required"
    module = importlib.import_module("capability_plugins.life_admin.plugin")
    return module.LifeAdminPlugin, module.LifeAdminPluginError


def _manifest():
    return next(
        manifest
        for manifest in load_manifests(MANIFEST_DIR)
        if manifest.plugin_id == "life_admin"
    )


def test_life_admin_manifest_is_dormant_and_never_writes_external_state():
    LifeAdminPlugin, _ = _api()
    manifest = _manifest()

    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.capability_permissions.keys() == set(EXPECTED_CAPABILITIES)
    assert manifest.capability_effects.keys() == set(EXPECTED_CAPABILITIES)
    assert manifest.capability_effects["life_admin.capture"] == "proposal"
    assert manifest.availability is Availability.INSTALLED
    assert manifest.activation_mode == "on_demand"
    assert manifest.enabled is True
    assert manifest.activation_state is ActivationState.DORMANT
    assert LifeAdminPlugin().manifest == manifest


def test_life_admin_item_schema_declares_only_the_five_supported_categories():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "LifeAdminItem"
    assert schema["properties"]["category"]["enum"] == list(EXPECTED_CATEGORIES)
    assert set(schema["required"]) >= {"item_id", "title", "category", "status"}


def test_domains_start_dormant_and_do_not_precreate_unmentioned_subdomains():
    LifeAdminPlugin, _ = _api()
    plugin = LifeAdminPlugin()

    result = plugin.invoke("life_admin.domains", {}, {})

    assert [item["domain_id"] for item in result["domains"]] == list(
        EXPECTED_CATEGORIES
    )
    assert all(item["activation_state"] == "dormant" for item in result["domains"])
    assert result["active_subdomains"] == []


def test_passport_expiry_activates_its_subdomain_and_returns_only_one_reminder():
    LifeAdminPlugin, _ = _api()
    plugin = LifeAdminPlugin()

    result = plugin.invoke(
        "life_admin.capture",
        {"text": "护照明年3月到期"},
        {"today": "2026-09-27"},
    )

    assert result["activated_subdomain"] == "identity_documents.passport"
    assert result["item"]["category"] == "identity_documents"
    assert result["item"]["subdomain"] == "passport"
    assert result["item"]["expires_at"] == "2027-03"
    assert result["item"]["persisted"] is False
    assert result["proposals"] == [
        {
            "proposal_type": "reminder",
            "title": "护照将于2027年3月到期",
            "due_at": "2027-03",
            "status": "pending_human_review",
            "executed": False,
            "requires_human_review": True,
        }
    ]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(result["item"]) <= set(schema["properties"])
    domains = plugin.invoke("life_admin.domains", {}, {})
    assert domains["active_subdomains"] == ["identity_documents.passport"]
    assert "automobile" not in json.dumps(result, ensure_ascii=False)
    assert "汽车" not in json.dumps(result, ensure_ascii=False)


def test_unrecognized_capture_does_not_activate_a_domain_or_create_a_record():
    LifeAdminPlugin, _ = _api()
    plugin = LifeAdminPlugin()

    result = plugin.invoke("life_admin.capture", {"text": "最近想把生活整理好"}, {})

    assert result == {
        "recognized": False,
        "activated_subdomain": None,
        "item": None,
        "proposals": [],
    }
    assert plugin.invoke("life_admin.domains", {}, {})["active_subdomains"] == []


@pytest.mark.parametrize(
    ("text", "context", "reason_code"),
    [
        ("护照2026年3月到期", {"today": "2026-09-27"}, "expiry_date_in_past"),
        ("护照3月到期", {"today": "2026-09-27"}, "expiry_year_required"),
        ("护照明年3月到期", {}, "reference_date_required"),
    ],
)
def test_ambiguous_or_past_expiry_requires_clarification_without_activation(
    text, context, reason_code
):
    LifeAdminPlugin, _ = _api()
    plugin = LifeAdminPlugin()

    result = plugin.invoke("life_admin.capture", {"text": text}, context)

    assert result == {
        "recognized": True,
        "needs_clarification": True,
        "reason_code": reason_code,
        "activated_subdomain": None,
        "item": None,
        "proposals": [],
    }
    assert plugin.invoke("life_admin.domains", {}, {})["active_subdomains"] == []


def test_life_admin_errors_are_stable_and_do_not_leak_input_or_provider_details():
    LifeAdminPlugin, LifeAdminPluginError = _api()

    with pytest.raises(LifeAdminPluginError) as invalid_error:
        LifeAdminPlugin().invoke("life_admin.capture", {"text": 42}, {})
    assert invalid_error.value.error_code == "invalid_input"

    with pytest.raises(LifeAdminPluginError) as capability_error:
        LifeAdminPlugin().invoke("life_admin.delete", {}, {})
    assert capability_error.value.error_code == "unsupported_capability"


def test_life_admin_plugin_has_no_direct_network_or_file_write_imports():
    LifeAdminPlugin, _ = _api()
    module = importlib.import_module("capability_plugins.life_admin.plugin")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_roots = {"subprocess", "requests", "urllib", "socket", "httpx"}
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    result = LifeAdminPlugin().invoke(
        "life_admin.capture", {"text": "护照明年3月到期"}, {"today": "2026-09-27"}
    )
    assert imported_roots.isdisjoint(forbidden_roots)
    assert all(proposal["executed"] is False for proposal in result["proposals"])
