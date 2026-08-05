from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import IntegrationAdapter


class ObsidianAdapter(IntegrationAdapter):
    name = "obsidian"

    def __init__(self, *, vault_path: str | Path, network_mode: str = "OFF") -> None:
        super().__init__(network_mode=network_mode)
        # Keep the constructor compatible with local configuration, but never
        # retain a Vault path in the adapter or expose a filesystem handle.
        Path(vault_path)

    def propose_write(
        self,
        *,
        title: str,
        body: str,
        yaml_schema: dict[str, Any],
        human: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        self._record("propose_write", correlation_id)
        if not title.strip() or not body.strip():
            raise ValueError("title and body are required")
        if not human.strip():
            raise ValueError("human reviewer is required")
        if not isinstance(yaml_schema, dict) or "id" not in yaml_schema:
            raise ValueError("yaml_schema must contain id")
        return {
            "proposal_type": "markdown_update",
            "title": title.strip(),
            "body": body,
            "yaml_schema": dict(yaml_schema),
            "status": "pending_human_review",
            "gateway": "knowledge",
            "target": "markdown_vault",
            "can_write": False,
            "requires_human_review": True,
            "human": human,
            "correlation_id": correlation_id,
        }

    def read_local(self, relative_path: str, *, correlation_id: str = "") -> str:
        self._record("read_local_denied", correlation_id)
        raise PermissionError(
            "Obsidian adapter cannot access the Vault directly; use Knowledge Gateway"
        )

    def read_via_gateway(
        self,
        gateway: Any,
        *,
        task: str,
        agent_id: str,
        credential: str,
        correlation_id: str = "",
    ) -> Any:
        self._record("read_via_gateway", correlation_id)
        return gateway.get_context(task, agent_id=agent_id, credential=credential)
