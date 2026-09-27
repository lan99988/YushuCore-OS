from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path
import re
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset({"finance.monthly_snapshot"})
_MONTH = re.compile(r"^(?!0000)([0-9]{4})-(0[1-9]|1[0-2])$")
_OCR_FIELDS = frozenset(
    {
        "currency",
        "total_income",
        "total_expenses",
        "consumption_structure",
        "large_expenses",
    }
)
_HISTORY_FIELDS = frozenset(
    {"month", "currency", "total_income", "total_expenses", "balance", "savings_rate"}
)
_ANALYSIS_FIELDS = frozenset({"anomalies", "ai_analysis", "next_month_focus"})
_CATEGORY_FIELDS = frozenset({"category", "amount"})


class FinancePluginError(ValueError):
    """Safe, stable errors exposed by Finance capability calls."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "finance":
            return manifest
    raise RuntimeError("finance manifest is missing")


class FinancePlugin:
    """Create a reviewable monthly aggregate proposal through injected ports."""

    def __init__(
        self,
        *,
        ocr_port: Any = None,
        history_port: Any = None,
        analysis_port: Any = None,
    ) -> None:
        _require_port(ocr_port, "extract_monthly_summary")
        _require_port(history_port, "previous_month_summary")
        _require_port(analysis_port, "analyze_monthly_snapshot")
        self.manifest = _load_manifest()
        self._ocr_port = ocr_port
        self._history_port = history_port
        self._analysis_port = analysis_port

    def invoke(
        self, capability: str, payload: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        del context
        if capability not in _CAPABILITIES:
            raise FinancePluginError("unsupported_capability")
        month, image_refs = _validate_request(payload)
        if self._ocr_port is None or self._analysis_port is None:
            raise FinancePluginError("finance_source_unavailable")

        try:
            ocr_result = self._ocr_port.extract_monthly_summary(
                image_refs, month=month
            )
        except Exception:
            raise FinancePluginError("finance_source_failed") from None
        ocr_summary = _validate_ocr_summary(ocr_result)
        previous = self._load_previous_month(month, ocr_summary["currency"])
        snapshot = _snapshot_from_aggregates(month, ocr_summary, previous)

        try:
            analysis_result = self._analysis_port.analyze_monthly_snapshot(
                _json_copy(snapshot), _json_copy(previous) if previous is not None else None
            )
        except Exception:
            raise FinancePluginError("finance_analysis_failed") from None
        snapshot.update(_validate_analysis(analysis_result))
        return {
            "proposal_type": "finance_monthly_snapshot",
            "snapshot": snapshot,
            "status": "pending_human_review",
            "executed": False,
            "requires_human_review": True,
        }

    def _load_previous_month(
        self, month: str, currency: str
    ) -> dict[str, Any] | None:
        if self._history_port is None:
            return None
        try:
            value = self._history_port.previous_month_summary(month)
        except Exception:
            raise FinancePluginError("finance_history_failed") from None
        if value is None:
            return None
        return _validate_history(value, month, currency)


def _require_port(port: Any, method: str) -> None:
    if port is not None and not callable(getattr(port, method, None)):
        raise TypeError(f"injected Finance port must provide {method}")


def _validate_request(payload: Any) -> tuple[str, tuple[str, ...]]:
    if type(payload) is not dict or set(payload) != {"month", "image_refs"}:
        raise FinancePluginError("invalid_payload")
    month = payload.get("month")
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise FinancePluginError("invalid_payload")
    refs = payload.get("image_refs")
    if (
        type(refs) is not list
        or not 1 <= len(refs) <= 12
        or any(not isinstance(ref, str) or not ref.strip() or len(ref) > 512 for ref in refs)
    ):
        raise FinancePluginError("invalid_payload")
    return month, tuple(ref.strip() for ref in refs)


def _validate_ocr_summary(value: Any) -> dict[str, Any]:
    data = _json_mapping(value, "invalid_ocr_summary")
    if set(data) != _OCR_FIELDS:
        raise FinancePluginError("invalid_ocr_summary")
    currency = data["currency"]
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise FinancePluginError("invalid_ocr_summary")
    income = _non_negative_number(data["total_income"])
    expenses = _non_negative_number(data["total_expenses"])
    structure = _validate_categories(data["consumption_structure"])
    if not structure or not math.isclose(
        sum(item["amount"] for item in structure), expenses, rel_tol=0, abs_tol=0.01
    ):
        raise FinancePluginError("invalid_ocr_summary")
    structure_by_category = {item["category"]: item["amount"] for item in structure}
    large_expenses = _validate_categories(data["large_expenses"])
    if any(
        item["category"] not in structure_by_category
        or not math.isclose(
            item["amount"],
            structure_by_category[item["category"]],
            rel_tol=0,
            abs_tol=0.01,
        )
        for item in large_expenses
    ):
        raise FinancePluginError("invalid_ocr_summary")
    return {
        "currency": currency,
        "total_income": income,
        "total_expenses": expenses,
        "consumption_structure": structure,
        "large_expenses": large_expenses,
    }


def _validate_categories(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise FinancePluginError("invalid_ocr_summary")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _CATEGORY_FIELDS:
            raise FinancePluginError("invalid_ocr_summary")
        category = item.get("category")
        if (
            not isinstance(category, str)
            or not category.strip()
            or len(category.strip()) > 80
            or category.strip() in seen
        ):
            raise FinancePluginError("invalid_ocr_summary")
        amount = _non_negative_number(item.get("amount"))
        result.append({"category": category.strip(), "amount": amount})
        seen.add(category.strip())
    return result


def _validate_history(
    value: Any, current_month: str, current_currency: str
) -> dict[str, Any]:
    data = _json_mapping(value, "invalid_history_summary")
    if set(data) != _HISTORY_FIELDS:
        raise FinancePluginError("invalid_history_summary")
    month = data.get("month")
    if (
        not isinstance(month, str)
        or _MONTH.fullmatch(month) is None
        or _previous_month(current_month) != month
        or data.get("currency") != current_currency
    ):
        raise FinancePluginError("invalid_history_summary")
    income = _non_negative_number(data["total_income"], "invalid_history_summary")
    expenses = _non_negative_number(data["total_expenses"], "invalid_history_summary")
    balance = _finite_number(data["balance"], "invalid_history_summary")
    rate = _finite_number(data["savings_rate"], "invalid_history_summary")
    if not math.isclose(balance, income - expenses, rel_tol=0, abs_tol=0.01):
        raise FinancePluginError("invalid_history_summary")
    expected_rate = balance / income if income else 0.0
    if not math.isclose(rate, expected_rate, rel_tol=0, abs_tol=1e-9):
        raise FinancePluginError("invalid_history_summary")
    return {
        "month": month,
        "currency": current_currency,
        "total_income": income,
        "total_expenses": expenses,
        "balance": balance,
        "savings_rate": rate,
    }


def _snapshot_from_aggregates(
    month: str, data: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    income = data["total_income"]
    expenses = data["total_expenses"]
    balance = income - expenses
    savings_rate = balance / income if income else 0.0
    return {
        "month": month,
        "currency": data["currency"],
        "total_income": income,
        "total_expenses": expenses,
        "balance": balance,
        "savings_rate": savings_rate,
        "consumption_structure": _with_shares(
            data["consumption_structure"], expenses
        ),
        "large_expenses": _with_shares(data["large_expenses"], expenses),
        "month_over_month": _month_over_month(income, expenses, savings_rate, previous),
    }


def _with_shares(
    categories: list[dict[str, Any]], total_expenses: float
) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "share": item["amount"] / total_expenses if total_expenses else 0.0,
        }
        for item in categories
    ]


def _month_over_month(
    income: float,
    expenses: float,
    savings_rate: float,
    previous: dict[str, Any] | None,
) -> dict[str, float | None]:
    if previous is None:
        return {
            "income_change_percent": None,
            "expenses_change_percent": None,
            "balance_change_percent": None,
            "savings_rate_change_percentage_points": None,
        }
    balance = income - expenses
    return {
        "income_change_percent": _percent_change(income, previous["total_income"]),
        "expenses_change_percent": _percent_change(expenses, previous["total_expenses"]),
        "balance_change_percent": _percent_change(balance, previous["balance"]),
        "savings_rate_change_percentage_points": (
            savings_rate - previous["savings_rate"]
        )
        * 100,
    }


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _validate_analysis(value: Any) -> dict[str, Any]:
    data = _json_mapping(value, "invalid_analysis")
    if set(data) != _ANALYSIS_FIELDS:
        raise FinancePluginError("invalid_analysis")
    anomalies = _text_list(data.get("anomalies"), "invalid_analysis")
    focus = _text_list(data.get("next_month_focus"), "invalid_analysis")
    summary = data.get("ai_analysis")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
        raise FinancePluginError("invalid_analysis")
    return {
        "anomalies": anomalies,
        "ai_analysis": summary.strip(),
        "next_month_focus": focus,
    }


def _text_list(value: Any, code: str) -> list[str]:
    if type(value) is not list or any(
        not isinstance(item, str) or not item.strip() or len(item) > 500 for item in value
    ):
        raise FinancePluginError(code)
    return [item.strip() for item in value]


def _json_mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinancePluginError(code)
    try:
        copied = json.loads(
            json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError, OverflowError):
        raise FinancePluginError(code) from None
    if not isinstance(copied, dict):
        raise FinancePluginError(code)
    return copied


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _non_negative_number(value: Any, code: str = "invalid_ocr_summary") -> int | float:
    number = _finite_number(value, code)
    if number < 0:
        raise FinancePluginError(code)
    return number


def _finite_number(value: Any, code: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinancePluginError(code)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise FinancePluginError(code)
    return value


def _previous_month(month: str) -> str:
    year, month_number = (int(value) for value in month.split("-"))
    if month_number == 1:
        year -= 1
        month_number = 12
    else:
        month_number -= 1
    return f"{year:04d}-{month_number:02d}"
