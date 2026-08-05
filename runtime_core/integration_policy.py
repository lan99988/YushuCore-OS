from __future__ import annotations

from dataclasses import dataclass


VALID_NETWORK_MODES = {"OFF", "ASSIST", "SYNC"}


@dataclass(frozen=True)
class IntegrationPolicy:
    network_mode: str = "OFF"

    def __post_init__(self) -> None:
        normalized = str(self.network_mode).upper()
        if normalized not in VALID_NETWORK_MODES:
            raise ValueError("network_mode must be OFF, ASSIST, or SYNC")
        object.__setattr__(self, "network_mode", normalized)

    @property
    def allows_local_runtime(self) -> bool:
        return True

    @property
    def allows_external_network(self) -> bool:
        return self.network_mode in {"ASSIST", "SYNC"}

    @property
    def allows_human_triggered_external_query(self) -> bool:
        return self.network_mode in {"ASSIST", "SYNC"}

    @property
    def allows_background_sync(self) -> bool:
        return self.network_mode == "SYNC"

    def route_external_data(self, source: str, content: str) -> dict[str, object]:
        if not self.allows_external_network:
            raise PermissionError("external data routing is disabled in OFF mode")
        if not source.strip() or not content.strip():
            raise ValueError("source and content are required")
        return {
            "source": source,
            "content": content,
            "destination": "00_Inbox",
            "status": "review_required",
            "review_required": True,
            "network_mode": self.network_mode,
        }
