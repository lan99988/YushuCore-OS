from __future__ import annotations

import ast
from typing import Protocol, get_type_hints
import json
from pathlib import Path

import pytest

from capability_plugins import ActivationState, load_manifests


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
SCHEMA_PATH = (
    ROOT
    / "04_数据中心（Data）"
    / "数据模型（Schema）"
    / "04_个人领域"
    / "FinanceMonthlySnapshot.json"
)
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "finance"
EXPECTED_CAPABILITIES = ("finance.monthly_snapshot",)


def _api():
    from capability_plugins.finance import FinancePlugin, FinancePluginError

    return FinancePlugin, FinancePluginError


def _manifest():
    return next(
        item
        for item in load_manifests(MANIFEST_DIR)
        if item.plugin_id == "finance"
    )


def _fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class FixtureOCRPort:
    def __init__(self):
        self.calls = []

    def extract_monthly_summary(self, image_refs, *, month):
        self.calls.append((tuple(image_refs), month))
        return _fixture("ocr_2026-09.json")


class FixtureHistoryPort:
    def __init__(self):
        self.calls = []

    def previous_month_summary(self, month):
        self.calls.append(month)
        return _fixture("history_2026-08.json")


class FixtureAnalysisPort:
    def __init__(self):
        self.calls = []

    def analyze_monthly_snapshot(self, snapshot, previous_summary):
        self.calls.append((snapshot, previous_summary))
        return _fixture("analysis_2026-09.json")


def _plugin():
    FinancePlugin, _ = _api()
    ocr = FixtureOCRPort()
    history = FixtureHistoryPort()
    analysis = FixtureAnalysisPort()
    return FinancePlugin(
        ocr_port=ocr,
        history_port=history,
        analysis_port=analysis,
    ), ocr, history, analysis


def test_finance_ports_define_injected_ocr_history_and_analysis_contracts():
    from capability_plugins.finance.ports import (
        FinanceAnalysisPort,
        FinanceHistoryPort,
        FinanceOCRPort,
    )

    assert all(
        issubclass(port, Protocol)
        for port in (FinanceOCRPort, FinanceHistoryPort, FinanceAnalysisPort)
    )
    assert "image_refs" in get_type_hints(
        FinanceOCRPort.extract_monthly_summary
    )
    assert "previous_month_summary" in FinanceHistoryPort.__dict__
    assert "analyze_monthly_snapshot" in FinanceAnalysisPort.__dict__


def test_finance_manifest_is_dormant_and_only_proposes_monthly_snapshots():
    FinancePlugin, _ = _api()
    manifest = _manifest()

    assert manifest.domain == "finance"
    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.activation_mode == "on_demand"
    assert manifest.activation_state is ActivationState.DORMANT
    assert manifest.permissions == ("read_finance", "propose_change")
    assert manifest.capability_effects == {
        "finance.monthly_snapshot": "proposal"
    }
    assert manifest.capability_permissions == {
        "finance.monthly_snapshot": ("read_finance", "propose_change")
    }
    assert FinancePlugin().manifest == manifest


def test_fixed_offline_fixtures_produce_a_reviewable_monthly_snapshot():
    plugin, ocr, history, analysis = _plugin()

    result = plugin.invoke(
        "finance.monthly_snapshot",
        {"month": "2026-09", "image_refs": ["fixture://2026-09"]},
        {"request_id": "finance-test"},
    )

    assert ocr.calls == [(('fixture://2026-09',), "2026-09")]
    assert history.calls == ["2026-09"]
    assert analysis.calls[0][0]["month"] == "2026-09"
    assert result == {
        "proposal_type": "finance_monthly_snapshot",
        "snapshot": _fixture("expected_snapshot_2026-09.json"),
        "status": "pending_human_review",
        "executed": False,
        "requires_human_review": True,
    }
    assert result["snapshot"]["total_income"] == 12000
    assert result["snapshot"]["total_expenses"] == 8000
    assert result["snapshot"]["balance"] == 4000
    assert result["snapshot"]["savings_rate"] == pytest.approx(1 / 3)
    assert plugin.manifest.writes == ()


def test_monthly_snapshot_schema_is_closed_and_contains_only_approved_aggregates():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    allowed = {
        "month",
        "currency",
        "total_income",
        "total_expenses",
        "balance",
        "savings_rate",
        "consumption_structure",
        "large_expenses",
        "month_over_month",
        "anomalies",
        "ai_analysis",
        "next_month_focus",
    }

    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["title"] == "FinanceMonthlySnapshot"
    assert set(schema["required"]) == allowed
    assert set(schema["properties"]) == allowed
    assert schema["additionalProperties"] is False
    assert "transactions" not in schema["properties"]
    assert "ledger" not in schema["properties"]
    assert set(schema["properties"]["consumption_structure"]["items"]["properties"]) == {
        "category",
        "amount",
        "share",
    }
    assert set(schema["properties"]["large_expenses"]["items"]["properties"]) == {
        "category",
        "amount",
        "share",
    }


def test_finance_plugin_rejects_transaction_level_data_and_unknown_fields():
    FinancePlugin, FinancePluginError = _api()
    ocr = FixtureOCRPort()
    plugin = FinancePlugin(
        ocr_port=ocr,
        history_port=FixtureHistoryPort(),
        analysis_port=FixtureAnalysisPort(),
    )

    def transaction_rows(_image_refs, *, month):
        return {
            **_fixture("ocr_2026-09.json"),
            "transactions": [{"date": "2026-09-01", "amount": 10}],
        }

    ocr.extract_monthly_summary = transaction_rows
    with pytest.raises(FinancePluginError) as error:
        plugin.invoke(
            "finance.monthly_snapshot",
            {"month": "2026-09", "image_refs": ["fixture://2026-09"]},
            {},
        )

    assert error.value.code == "invalid_ocr_summary"
    assert "2026-09-01" not in str(error.value)
    assert error.value.__cause__ is None


def test_large_expenses_are_category_totals_not_individual_purchase_amounts():
    FinancePlugin, FinancePluginError = _api()
    ocr = FixtureOCRPort()
    plugin = FinancePlugin(
        ocr_port=ocr,
        history_port=FixtureHistoryPort(),
        analysis_port=FixtureAnalysisPort(),
    )
    individual_purchase = _fixture("ocr_2026-09.json")
    individual_purchase["large_expenses"] = [{"category": "餐饮", "amount": 1200}]
    ocr.extract_monthly_summary = lambda *_args, **_kwargs: individual_purchase

    with pytest.raises(FinancePluginError) as error:
        plugin.invoke(
            "finance.monthly_snapshot",
            {"month": "2026-09", "image_refs": ["fixture://2026-09"]},
            {},
        )

    assert error.value.code == "invalid_ocr_summary"


def test_non_finite_range_ocr_amount_is_rejected_with_a_stable_error():
    FinancePlugin, FinancePluginError = _api()
    ocr = FixtureOCRPort()
    plugin = FinancePlugin(
        ocr_port=ocr,
        history_port=FixtureHistoryPort(),
        analysis_port=FixtureAnalysisPort(),
    )
    oversized_summary = _fixture("ocr_2026-09.json")
    oversized_summary["total_income"] = 10**1000
    ocr.extract_monthly_summary = lambda *_args, **_kwargs: oversized_summary

    with pytest.raises(FinancePluginError) as error:
        plugin.invoke(
            "finance.monthly_snapshot",
            {"month": "2026-09", "image_refs": ["fixture://2026-09"]},
            {},
        )

    assert error.value.code == "invalid_ocr_summary"
    assert error.value.__cause__ is None


def test_finance_plugin_fails_closed_when_ports_are_unconfigured_or_fail():
    FinancePlugin, FinancePluginError = _api()
    request = {"month": "2026-09", "image_refs": ["fixture://2026-09"]}

    with pytest.raises(FinancePluginError) as missing:
        FinancePlugin().invoke("finance.monthly_snapshot", request, {})
    assert missing.value.code == "finance_source_unavailable"

    class BrokenOCR:
        def extract_monthly_summary(self, *_args, **_kwargs):
            raise RuntimeError("private screenshot OCR contents")

    plugin = FinancePlugin(
        ocr_port=BrokenOCR(),
        history_port=FixtureHistoryPort(),
        analysis_port=FixtureAnalysisPort(),
    )
    with pytest.raises(FinancePluginError) as failure:
        plugin.invoke("finance.monthly_snapshot", request, {})
    assert failure.value.code == "finance_source_failed"
    assert "private screenshot OCR contents" not in str(failure.value)
    assert failure.value.__cause__ is None


def test_finance_plugin_rejects_invalid_requests_without_calling_ocr():
    FinancePlugin, FinancePluginError = _api()
    plugin, ocr, *_ = _plugin()

    for payload in (
        {"month": "2026-13", "image_refs": ["fixture://2026-09"]},
        {"month": "0000-01", "image_refs": ["fixture://2026-09"]},
        {"month": "２０２６-09", "image_refs": ["fixture://2026-09"]},
        {"month": "2026-09", "image_refs": []},
        {"month": "2026-09", "image_refs": ["fixture://2026-09"], "transactions": []},
    ):
        with pytest.raises(FinancePluginError) as error:
            plugin.invoke("finance.monthly_snapshot", payload, {})
        assert error.value.code == "invalid_payload"

    assert ocr.calls == []


def test_finance_plugin_has_no_direct_network_or_file_io_imports():
    _api()
    import capability_plugins.finance.plugin as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_roots = {
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(forbidden_roots)
