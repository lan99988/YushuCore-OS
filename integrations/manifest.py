from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationManifest:
    integration: str
    read: bool
    write: bool
    risk: str

    def __post_init__(self) -> None:
        if not self.integration.strip():
            raise ValueError("integration is required")
        if self.risk not in {"low", "medium", "high"}:
            raise ValueError("risk must be low, medium, or high")

    def to_dict(self) -> dict[str, object]:
        return {
            "integration": self.integration,
            "permission": {"read": self.read, "write": self.write},
            "risk": self.risk,
        }
