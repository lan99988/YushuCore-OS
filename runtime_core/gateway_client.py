from __future__ import annotations

from typing import Any


class KnowledgeGatewayClient:
    """Runtime-facing facade for Knowledge Gateway access.

    Runtime services depend on this client instead of the concrete gateway so
    the architecture keeps a stable boundary:
    Runtime -> Knowledge Gateway Client -> Knowledge Gateway.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def get_context(self, *args, **kwargs):
        return self._gateway.get_context(*args, **kwargs)

    def get_context_with_access_grant(self, *args, **kwargs):
        return self._gateway.get_context_with_access_grant(*args, **kwargs)

    def request_update(self, *args, **kwargs):
        return self._gateway.request_update(*args, **kwargs)

    def approve_change(self, *args, **kwargs):
        return self._gateway.approve_change(*args, **kwargs)

    def reject_change(self, *args, **kwargs):
        return self._gateway.reject_change(*args, **kwargs)

    def expire_change(self, *args, **kwargs):
        return self._gateway.expire_change(*args, **kwargs)
