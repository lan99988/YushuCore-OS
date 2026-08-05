from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntegrationCall:
    adapter: str
    operation: str
    correlation_id: str
    network_mode: str


class IntegrationAdapter:
    name = "integration"

    def __init__(self, *, network_mode: str = "OFF") -> None:
        normalized = str(network_mode).upper()
        if normalized not in {"OFF", "ASSIST", "SYNC"}:
            raise ValueError("network_mode must be OFF, ASSIST, or SYNC")
        self.network_mode = normalized
        self.calls: list[IntegrationCall] = []

    def _record(self, operation: str, correlation_id: str = "") -> IntegrationCall:
        call = IntegrationCall(
            adapter=self.name,
            operation=operation,
            correlation_id=correlation_id,
            network_mode=self.network_mode,
        )
        self.calls.append(call)
        return call

    def _require_local(self) -> None:
        if self.network_mode != "OFF":
            return

    def _require_assist_or_sync(self) -> None:
        if self.network_mode not in {"ASSIST", "SYNC"}:
            raise AdapterError("external integration requires ASSIST or SYNC network mode")
