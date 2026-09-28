from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

from yushu_app.application import YushuApplication
from yushu_app.mcp_server import handle_request, serve_stdio
from yushu_app.profile import Profile


META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "test-agent", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {}}


def _request(method: str, params: dict, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {**params, "_meta": META}}


def test_mcp_discovers_all_capabilities_and_six_flows(tmp_path: Path):
    app = YushuApplication(Profile.initialize("test", home=tmp_path))
    discovery = handle_request(app, _request("server/discover", {}))
    assert discovery["result"]["supportedVersions"] == ["2026-07-28"]
    listed = handle_request(app, _request("tools/list", {}))
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"local_record.create", "knowledge.search", "task.list", "flow.capture", "flow.today"} <= names
    assert len([name for name in names if name.startswith("flow.")]) == 6
    assert all(tool["inputSchema"]["type"] == "object" for tool in listed["result"]["tools"])


def test_mcp_and_cli_core_return_same_business_result_and_errors(tmp_path: Path):
    app = YushuApplication(Profile.initialize("test", home=tmp_path))
    called = handle_request(app, _request("tools/call", {"name": "local_record.create",
        "arguments": {"agent_id": "agent-a", "payload": {"kind": "task", "data": {"title": "写周报"}},
                      "correlation_id": "corr-create"}}))
    assert called["result"]["isError"] is False
    assert called["result"]["structuredContent"]["status"] == "completed"
    missing = handle_request(app, _request("tools/call", {"name": "task.list",
        "arguments": {"agent_id": "agent-a", "payload": {}, "correlation_id": "corr-missing"}}))
    assert missing["result"]["isError"] is True
    assert missing["result"]["structuredContent"]["error_code"] == "plugin_executor_missing"


def test_stdio_contains_only_json_rpc_messages(tmp_path: Path):
    app = YushuApplication(Profile.initialize("test", home=tmp_path))
    incoming = StringIO(json.dumps(_request("server/discover", {})) + "\n")
    outgoing = StringIO()
    serve_stdio(app, incoming=incoming, outgoing=outgoing)
    lines = outgoing.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["jsonrpc"] == "2.0"
