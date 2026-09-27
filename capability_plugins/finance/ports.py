from __future__ import annotations

from typing import Any, Mapping, Protocol


class FinanceOCRPort(Protocol):
    """Host-supplied OCR/vision adapter for monthly aggregate extraction."""

    def extract_monthly_summary(
        self, image_refs: tuple[str, ...], *, month: str
    ) -> Mapping[str, Any]:
        raise NotImplementedError


class FinanceHistoryPort(Protocol):
    """Read-only source for the preceding month's aggregate snapshot."""

    def previous_month_summary(self, month: str) -> Mapping[str, Any] | None:
        raise NotImplementedError


class FinanceAnalysisPort(Protocol):
    """Analysis adapter that receives monthly aggregates, never transaction rows."""

    def analyze_monthly_snapshot(
        self,
        snapshot: Mapping[str, Any],
        previous_summary: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        raise NotImplementedError
