from __future__ import annotations

from typing import Any
import hashlib
import json
from threading import Lock

from .base import AdapterError, IntegrationAdapter


class FeishuAdapter(IntegrationAdapter):
    name = "feishu"

    def __init__(self, *, client: Any | None = None, network_mode: str = "ASSIST",
                 enable_external_writes: bool = False) -> None:
        super().__init__(network_mode=network_mode)
        self.client = client
        self.enable_external_writes = enable_external_writes
        self._submitted: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

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
        if not self.enable_external_writes or self.client is None:
            raise AdapterError("feishu external write is unverified or client is missing")
        body = {key: proposal.get(key, "") for key in ("title", "project_id", "assignee", "due_at")}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
        with self._lock:
            if idempotency_key in self._submitted:
                previous = self._submitted[idempotency_key]
                if previous["request_digest"] != digest:
                    raise AdapterError("idempotency key reused for a different feishu task")
                return dict(previous)
            external = self.client.create_task(body, idempotency_key=idempotency_key)
            if not isinstance(external, dict) or not external.get("task_id"):
                raise AdapterError("feishu client did not confirm a task_id")
            result = {"status": "submitted", "proposal_id": proposal_id,
                      "external_system": "feishu", "idempotency_key": idempotency_key,
                      "correlation_id": proposal.get("correlation_id", ""),
                      "title": proposal.get("title", ""), "external": external,
                      "request_digest": digest}
            self._submitted[idempotency_key] = dict(result)
            return result

    def notify(self, *, message: str, correlation_id: str = "") -> dict[str, Any]:
        if self.network_mode == "OFF":
            raise AdapterError("feishu integration is disabled in OFF mode")
        if not message.strip():
            raise ValueError("message is required")
        if not self.enable_external_writes or self.client is None:
            raise AdapterError("feishu external write is unverified or client is missing")
        external = self.client.notify(message)
        if not isinstance(external, dict) or not external.get("message_id"):
            raise AdapterError("feishu client did not confirm a message_id")
        return {"status": "submitted", "external_system": "feishu",
                "message": message, "correlation_id": correlation_id, "external": external}
