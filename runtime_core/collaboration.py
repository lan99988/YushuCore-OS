from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime_core.events import EventBus


class AgentEventRelay:
    """Routes Agent collaboration through EventBus instead of direct Agent calls."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._subscriptions: dict[str, list[tuple[str, Callable[[dict[str, Any]], None]]]] = {}

    def subscribe(
        self,
        target_agent: str,
        event_type: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        self._subscriptions.setdefault(event_type, []).append((target_agent, handler))

    def emit(
        self,
        source_agent: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str = "",
    ) -> None:
        subscriptions = self._subscriptions.get(event_type, [])
        if not subscriptions:
            self.event_bus.publish(
                {
                    "event": event_type,
                    "source_agent": source_agent,
                    "target_agent": None,
                    "payload": dict(payload),
                    "correlation_id": correlation_id,
                }
            )
            return
        for target_agent, handler in subscriptions:
            event = {
                "event": event_type,
                "source_agent": source_agent,
                "target_agent": target_agent,
                "payload": dict(payload),
                "correlation_id": correlation_id,
            }
            self.event_bus.publish(event)
            handler(dict(event))
