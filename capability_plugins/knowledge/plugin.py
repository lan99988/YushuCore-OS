from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests
from knowledge_system.gateway import KnowledgeGateway, PermissionDenied
from knowledge_system.gateway.ima_service import KnowledgeUnavailable
from knowledge_system.gateway.models import ContextResponse, GatewayNode, QueryResponse


_CAPABILITIES = frozenset(
    {
        "knowledge.search",
        "knowledge.list",
        "knowledge.get",
        "knowledge.evidence_context",
        "knowledge.read_context",
        "knowledge.get_schema",
        "knowledge.health",
    }
)


class KnowledgePluginError(ValueError):
    """Safe, stable error raised by the read-only Knowledge adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.error_code = code
        super().__init__(code)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "knowledge":
            return manifest
    raise RuntimeError("knowledge manifest is missing")


class KnowledgePlugin:
    """Expose search and evidence only through the injected KnowledgeGateway."""

    def __init__(
        self,
        gateway: KnowledgeGateway,
        *,
        agent_id: str,
        credential: str,
    ) -> None:
        if not callable(getattr(gateway, "query_knowledge", None)) or not callable(
            getattr(gateway, "get_context", None)
        ):
            raise TypeError("gateway must provide query_knowledge and get_context")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        if not isinstance(credential, str) or not credential.strip():
            raise ValueError("credential is required")
        self.manifest = _load_manifest()
        self._gateway = gateway
        self._agent_id = agent_id
        self._credential = credential

    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> Any:
        del context
        if capability not in _CAPABILITIES:
            raise KnowledgePluginError("unsupported_capability")
        if type(payload) is not dict:
            raise KnowledgePluginError("invalid_payload")
        if capability == "knowledge.health":
            health = getattr(self._gateway, "health", None)
            return health() if callable(health) else {"status": "available"}
        if capability == "knowledge.get_schema":
            self._required_text(payload, "node_id", "invalid_node_id")
            # The current Gateway has no authorized schema API. Fail closed
            # rather than reading repository metadata around that boundary.
            raise KnowledgePluginError("schema_unavailable")
        if capability in {"knowledge.search", "knowledge.list"}:
            if capability == "knowledge.list":
                list_method = getattr(self._gateway, "list_knowledge", None)
                response = self._gateway_call(list_method) if callable(list_method) else self._query("")
            else:
                query = self._required_text(payload, "query", "invalid_query")
                response = self._query(query)
            _validate_query_response(response)
            nodes = response.nodes
            if "time_range" in payload:
                start, end = _parse_time_range(payload.get("time_range"))
                nodes = [
                    node
                    for node in nodes
                    if (observed := _observed_date(node)) is not None
                    and start <= observed <= end
                ]
            return {
                "nodes": [_node_projection(node) for node in nodes],
                "permission": response.permission,
                "denied_count": response.denied_count,
                "invalid_count": response.invalid_count,
                **({"source": response.source, "stale": response.stale,
                    "partial": response.partial, "cached_at": response.cached_at,
                    **({"warning": "结果可能不完整"} if response.stale or response.partial else {})}
                   if response.source else {}),
            }
        if capability == "knowledge.get":
            node_id = self._required_text(payload, "node_id", "invalid_node_id")
            get_method = getattr(self._gateway, "get_node", None)
            # Legacy gateways retain their authorized query view during migration.
            response = self._gateway_call(get_method, node_id) if callable(get_method) else self._query("")
            _validate_query_response(response)
            node = next((item for item in response.nodes if item.id == node_id), None)
            if node is None:
                raise KnowledgePluginError("node_not_found")
            result = _node_projection(node)
            if response.source:
                result.update(source=response.source, stale=response.stale,
                              partial=response.partial, cached_at=response.cached_at)
                if response.stale or response.partial:
                    result["warning"] = "结果可能不完整"
            return result

        task = self._required_text(payload, "task", "invalid_task")
        try:
            response = self._gateway.get_context(
                task, agent_id=self._agent_id, credential=self._credential
            )
        except PermissionDenied:
            raise KnowledgePluginError("permission_denied") from None
        except KnowledgeUnavailable as exc:
            raise KnowledgePluginError(exc.reason_code) from None
        except Exception:
            raise KnowledgePluginError("gateway_unavailable") from None
        if not isinstance(response, ContextResponse) or any(
            not isinstance(node, GatewayNode)
            for group in (response.knowledge, response.experience, response.principles)
            for node in group
        ):
            raise KnowledgePluginError("invalid_gateway_response")
        return {
            "knowledge": [_node_projection(node) for node in response.knowledge],
            "experience": [_node_projection(node) for node in response.experience],
            "principles": [_node_projection(node) for node in response.principles],
        }

    def _query(self, query: str) -> QueryResponse:
        try:
            return self._gateway.query_knowledge(
                query, agent_id=self._agent_id, credential=self._credential
            )
        except PermissionDenied:
            raise KnowledgePluginError("permission_denied") from None
        except KnowledgeUnavailable as exc:
            raise KnowledgePluginError(exc.reason_code) from None
        except Exception:
            raise KnowledgePluginError("gateway_unavailable") from None

    def _gateway_call(self, method: Any, *args: Any) -> QueryResponse:
        try:
            return method(*args, agent_id=self._agent_id, credential=self._credential)
        except PermissionDenied:
            raise KnowledgePluginError("permission_denied") from None
        except KnowledgeUnavailable as exc:
            raise KnowledgePluginError(exc.reason_code) from None
        except Exception:
            raise KnowledgePluginError("gateway_unavailable") from None

    @staticmethod
    def _required_text(
        payload: dict[str, Any], field_name: str, error_code: str
    ) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise KnowledgePluginError(error_code)
        return value.strip()


def _node_projection(node: GatewayNode) -> dict[str, Any]:
    projection = {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "domain": list(node.domain),
        "status": node.status,
        "confidence": node.confidence,
        "sensitivity": node.sensitivity,
        "content": node.body,
    }
    observed = _observed_date(node)
    if observed is not None:
        projection["observed_at"] = observed.isoformat()
    return projection


def _parse_time_range(value: Any) -> tuple[date, date]:
    if not isinstance(value, str):
        raise KnowledgePluginError("invalid_time_range")
    parts = value.split("/", 1)
    if len(parts) != 2:
        raise KnowledgePluginError("invalid_time_range")
    try:
        start, end = (date.fromisoformat(part) for part in parts)
    except ValueError:
        raise KnowledgePluginError("invalid_time_range") from None
    if start > end:
        raise KnowledgePluginError("invalid_time_range")
    return start, end


def _observed_date(node: GatewayNode) -> date | None:
    metadata = node.metadata
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("updated") or metadata.get("created")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_query_response(response: Any) -> None:
    if not isinstance(response, QueryResponse):
        raise KnowledgePluginError("invalid_gateway_response")
    if (
        not isinstance(response.permission, str)
        or not isinstance(response.nodes, list)
        or type(response.denied_count) is not int
        or response.denied_count < 0
        or type(response.invalid_count) is not int
        or response.invalid_count < 0
    ):
        raise KnowledgePluginError("invalid_gateway_response")
    if response.permission != "approved":
        raise KnowledgePluginError("permission_denied")
    if any(not _valid_query_node(node) for node in response.nodes):
        raise KnowledgePluginError("invalid_gateway_response")


def _valid_query_node(node: Any) -> bool:
    if not isinstance(node, GatewayNode):
        return False
    if not all(
        isinstance(value, str)
        for value in (
            node.id,
            node.type,
            node.title,
            node.status,
            node.sensitivity,
            node.body,
        )
    ):
        return False
    if not isinstance(node.domain, tuple) or not all(
        isinstance(domain, str) for domain in node.domain
    ):
        return False
    return (
        type(node.confidence) in {int, float}
        and math.isfinite(node.confidence)
        and 0 <= node.confidence <= 1
    )
