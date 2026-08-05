from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AdapterError, IntegrationAdapter


class LlmWikiAdapter(IntegrationAdapter):
    name = "llm_wiki"

    def __init__(
        self,
        *,
        exe_path: str | Path,
        client: Any | None = None,
        network_mode: str = "OFF",
    ) -> None:
        super().__init__(network_mode=network_mode)
        self.exe_path = Path(exe_path)
        self.client = client

    def health(self, *, correlation_id: str = "") -> dict[str, Any]:
        self._record("health", correlation_id)
        result = {
            "mode": "read_only",
            "gateway_first": True,
            "executable": self.exe_path.name,
            "writable": False,
        }
        if self.client is not None:
            result["service"] = self.client.health()
        return result

    def search(
        self,
        query: str,
        *,
        scope: str = "",
        limit: int = 20,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._record("search", correlation_id)
        if not query.strip():
            raise ValueError("query is required")
        if limit < 1:
            raise ValueError("limit must be positive")
        if self.client is None:
            return {"query": query, "scope": scope, "limit": limit, "nodes": []}
        return self.client.search("current", query, {"topK": limit, "includeContent": False})

    def read_context(
        self,
        task: str,
        *,
        scope: str = "",
        max_sensitivity: str = "level_0",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._record("read_context", correlation_id)
        if not task.strip():
            raise ValueError("task is required")
        result = {
            "task": task,
            "scope": scope,
            "max_sensitivity": max_sensitivity,
            "nodes": [],
        }
        if self.client is not None:
            result["context"] = self.client.search(
                "current",
                task,
                {"topK": 20, "includeContent": True},
            )
        return result

    def get_schema(self, node_id: str, *, correlation_id: str = "") -> dict[str, Any]:
        self._record("get_schema", correlation_id)
        if not node_id.strip():
            raise ValueError("node_id is required")
        return {"node_id": node_id, "schema": None}

    def read_file(self, path: str, *, correlation_id: str = "") -> dict[str, Any]:
        self._record("read_file", correlation_id)
        raise PermissionError(
            "llm_wiki file operations are forbidden; use Gateway knowledge read APIs"
        )

    def write_knowledge(self, node_id: str, content: str) -> None:
        raise PermissionError("llm_wiki adapter is read-only; write is forbidden")

    def execute_external(self, operation: str, **kwargs: Any) -> Any:
        if self.network_mode == "OFF":
            raise AdapterError("external llm_wiki execution is disabled in OFF mode")
        raise AdapterError("llm_wiki executable execution is not enabled by this adapter")
