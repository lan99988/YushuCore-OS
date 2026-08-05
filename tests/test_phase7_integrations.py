from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_obsidian_environment_discovers_open_vault_without_editing_it(tmp_path: Path):
    from integrations.obsidian_environment import ObsidianEnvironment

    config = tmp_path / "obsidian.json"
    vault = tmp_path / "vault"
    vault.mkdir()
    config.write_text(json.dumps({"vaults": {"v1": {"path": str(vault), "open": True}}}), encoding="utf-8")

    environment = ObsidianEnvironment(installation_path=tmp_path, config_path=config)
    result = environment.inspect()

    assert result["installation"] == str(tmp_path)
    assert result["open_vault"] == str(vault)
    assert result["writable_by_adapter"] is False


def test_ollama_local_client_uses_local_api_and_never_cloud_route():
    from integrations.ollama import OllamaClient

    class Response:
        status = 200

        def read(self):
            return b'{"model":"qwen","response":"local result","done":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = OllamaClient(opener=lambda request, timeout: Response())
    result = client.generate("qwen", "analyze")

    assert result["response"] == "local result"
    assert client.route(sensitivity="level_4")["provider"] == "local"


def test_mcp_knowledge_server_exposes_read_tools_only():
    from integrations.mcp import KnowledgeMcpServer

    server = KnowledgeMcpServer()
    names = {item["name"] for item in server.tools()}

    assert names == {"knowledge.search", "knowledge.read_context", "knowledge.get_schema", "knowledge.health"}
    assert all("write" not in item["name"] and "file" not in item["name"] for item in server.tools())


def test_capture_adapter_routes_external_data_to_inbox_review():
    from integrations.capture import CaptureAdapter

    captured = []
    adapter = CaptureAdapter(writer=captured.append)
    result = adapter.capture(source="web", content="new knowledge", title="Note", correlation_id="corr")

    assert result["destination"] == "00_Inbox"
    assert result["status"] == "review_required"
    assert captured[0]["source"] == "web"


def test_integration_manifest_declares_permission_and_risk():
    from integrations.manifest import IntegrationManifest

    manifest = IntegrationManifest("obsidian", read=True, write=False, risk="low")

    assert manifest.to_dict() == {"integration": "obsidian", "permission": {"read": True, "write": False}, "risk": "low"}
    with pytest.raises(ValueError):
        IntegrationManifest("bad", read=False, write=False, risk="critical")
