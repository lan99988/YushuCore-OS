from __future__ import annotations

from typing import Any

from .base import AdapterError, IntegrationAdapter


class FeishuAdapter(IntegrationAdapter):
    name = "feishu"

    def __init__(self, *, client: Any | None = None, network_mode: str = "ASSIST") -> None:
        super().__init__(network_mode=network_mode)
        self.client = client
        self._submitted: dict[str, dict[str, Any]] = {}

    def submit_task(self, proposal: dict[str, Any]) -> dict[str, Any]:
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        if not proposal_id:
            raise ValueError("proposal_id is required")
        if proposal.get("status") != "approved":
            raise PermissionError("only approved proposals may be submitted to feishu")
        idempotency_key = str(proposal.get("idempotency_key", "")).strip()
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if self.network_mode == "OFF":
            raise AdapterError("feishu integration is disabled in OFF mode")
        if idempotency_key in self._submitted:
            return dict(self._submitted[idempotency_key])
        result = {
            "status": "submitted",
            "proposal_id": proposal_id,
            "external_system": "feishu",
            "idempotency_key": idempotency_key,
            "correlation_id": proposal.get("correlation_id", ""),
            "title": proposal.get("title", ""),
        }
        if self.client is not None:
            result["external"] = self.client.create_task(
                {
                    "title": proposal.get("title", ""),
                    "project_id": proposal.get("project_id", ""),
                    "assignee": proposal.get("assignee", ""),
                    "due_at": proposal.get("due_at", ""),
                },
                idempotency_key=idempotency_key,
            )
        self._submitted[idempotency_key] = dict(result)
        return result

    def notify(self, *, message: str, correlation_id: str = "") -> dict[str, Any]:
        if self.network_mode == "OFF":
            raise AdapterError("feishu integration is disabled in OFF mode")
        if not message.strip():
            raise ValueError("message is required")
        result = {
            "status": "queued",
            "external_system": "feishu",
            "message": message,
            "correlation_id": correlation_id,
        }
        if self.client is not None:
            result["external"] = self.client.notify(message)
        return result
