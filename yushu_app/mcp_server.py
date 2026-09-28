"""Local stdio MCP transport; stdout contains JSON-RPC only.

Supports the 2026-07-28 per-request-metadata protocol and the 2025-06-18
initialize handshake for older desktop clients. No HTTP listener is opened.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .application import YushuApplication


VERSION = "2026-07-28"
LEGACY_VERSION = "2025-06-18"
FLOW_NAMES = ("capture", "plan", "today", "adjust", "review", "explore")
OUTPUT_SCHEMA = {"type": "object", "properties": {"schema_version": {"type": "integer"},
    "status": {"type": "string"}}, "required": ["schema_version", "status"]}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _schema_for(capability: str, manifest: Any) -> dict[str, Any]:
    inner = manifest.input_contract.get(capability, {"type": "object"})
    if not isinstance(inner, dict) or inner.get("type") != "object":
        inner = {"type": "object"}
    return {"type": "object", "properties": {
        "agent_id": {"type": "string", "minLength": 1},
        "correlation_id": {"type": "string"},
        "payload": inner,
        "dry_run": {"type": "boolean"},
    }, "required": ["agent_id", "payload"], "additionalProperties": False}


def _tools(app: YushuApplication) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for manifest in app.manifests:
        for capability in manifest.provides:
            entries.append({"name": capability, "title": capability,
                "description": manifest.purpose + (
                    " [当前未装配，调用返回 plugin_executor_missing]"
                    if manifest.plugin_id not in {"local_record", "knowledge"} else ""),
                "inputSchema": _schema_for(capability, manifest), "outputSchema": OUTPUT_SCHEMA})
    for flow in FLOW_NAMES:
        entries.append({"name": f"flow.{flow}", "title": flow.title(),
            "description": f"Yushu-OS {flow} 用户逻辑链",
            "inputSchema": {"type": "object", "properties": {
                "agent_id": {"type": "string"}, "text": {"type": "string"},
                "context": {"type": "object"}, "correlation_id": {"type": "string"},
                "dry_run": {"type": "boolean"}},
                "required": ["agent_id", "text"], "additionalProperties": False},
            "outputSchema": OUTPUT_SCHEMA})
    return sorted(entries, key=lambda item: item["name"])


def _validate_meta(params: dict[str, Any]) -> bool:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return False
    return (meta.get("io.modelcontextprotocol/protocolVersion") == VERSION
            and isinstance(meta.get("io.modelcontextprotocol/clientInfo"), dict)
            and isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict))


def handle_request(app: YushuApplication, request: Any) -> dict[str, Any] | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid Request")
    request_id = request.get("id")
    if isinstance(request_id, bool) or not (request_id is None or isinstance(request_id, (str, int))):
        return _error(None, -32600, "Invalid Request")
    method = request.get("method")
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid Request")
    if request_id is None:
        return None  # notifications never receive a response
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params")
    legacy = method == "initialize" or ("_meta" not in params and method in {"tools/list", "tools/call"})
    if method == "initialize":
        if params.get("protocolVersion") != LEGACY_VERSION:
            return _error(request_id, -32602, "Unsupported protocol version")
        return _response(request_id, {"protocolVersion": LEGACY_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "yushu-os", "version": "0.1.0"}})
    if not legacy and not _validate_meta(params):
        return _error(request_id, -32602, "Invalid request metadata")
    if method == "server/discover":
        return _response(request_id, {"resultType": "complete", "supportedVersions": [VERSION],
            "capabilities": {"tools": {"listChanged": False}},
            "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "yushu-os", "version": "0.1.0"}}})
    if method == "tools/list":
        if params.get("cursor") not in (None, ""):
            return _error(request_id, -32602, "Invalid cursor")
        return _response(request_id, {**({} if legacy else {"resultType": "complete"}),
                                      "tools": _tools(app)})
    if method != "tools/call":
        return _error(request_id, -32601, "Method not found")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return _error(request_id, -32602, "Invalid params")
    if name not in {entry["name"] for entry in _tools(app)}:
        return _error(request_id, -32602, "Unknown tool")
    agent_id = arguments.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return _error(request_id, -32602, "agent_id is required")
    correlation_id = arguments.get("correlation_id")
    dry_run = arguments.get("dry_run", False)
    if correlation_id is not None and not isinstance(correlation_id, str):
        return _error(request_id, -32602, "Invalid correlation_id")
    if type(dry_run) is not bool:
        return _error(request_id, -32602, "Invalid dry_run")
    if name.startswith("flow."):
        text = arguments.get("text")
        context = arguments.get("context", {})
        if not isinstance(text, str) or not isinstance(context, dict):
            return _error(request_id, -32602, "Invalid flow arguments")
        result = app.run_flow(name[5:], text, context=context, agent_id=agent_id,
                              correlation_id=correlation_id, dry_run=dry_run)
    else:
        payload = arguments.get("payload")
        if not isinstance(payload, dict):
            return _error(request_id, -32602, "payload must be an object")
        result = app.invoke_capability(name, payload, agent_id=agent_id,
                                       correlation_id=correlation_id, dry_run=dry_run)
    return _response(request_id, {**({} if legacy else {"resultType": "complete"}),
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result, "isError": result["status"] not in {"completed", "dry_run"}})


def serve_stdio(app: YushuApplication, *, incoming: TextIO | None = None,
                outgoing: TextIO | None = None) -> None:
    source = incoming or sys.stdin
    destination = outgoing or sys.stdout
    if destination is sys.stdout and callable(getattr(destination, "reconfigure", None)):
        destination.reconfigure(encoding="utf-8", newline="\n")
    for line in source:
        try:
            request = json.loads(line)
            response = handle_request(app, request)
        except json.JSONDecodeError:
            response = _error(None, -32700, "Parse error")
        except Exception:
            response = _error(None, -32603, "Internal error")
        if response is not None:
            destination.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
            destination.flush()
