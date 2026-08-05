from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LifeDataRequest:
    scope: str
    agent_id: str
    sensitivity: str

    def __post_init__(self) -> None:
        if not self.scope.strip() or not self.agent_id.strip():
            raise ValueError("scope and agent_id are required")
        if self.sensitivity not in {"level_0", "level_1", "level_2", "level_3", "level_4"}:
            raise ValueError("invalid sensitivity")


class LifeDatabasePort:
    """Reserved boundary for future life data; no external source is connected."""

    def read(self, request: LifeDataRequest):
        raise NotImplementedError("Life Database interface is reserved for a future phase")


class LifeDatabaseGateway:
    def __init__(self, gateway) -> None:
        self._gateway = gateway

    def read(self, request: LifeDataRequest, *, credential: str):
        return self._gateway.get_context_with_access_grant(
            request.scope,
            agent_id=request.agent_id,
            credential=credential,
            resource_path=f"life/{request.scope}",
            max_sensitivity=request.sensitivity,
        )
