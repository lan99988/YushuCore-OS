from __future__ import annotations

from collections.abc import Callable
from typing import Any


EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []
        self._history: list[dict[str, Any]] = []

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def publish(self, event: dict[str, Any]) -> None:
        snapshot = dict(event)
        self._history.append(snapshot)
        for handler in self._subscribers:
            handler(dict(snapshot))
