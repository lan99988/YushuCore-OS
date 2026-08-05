from __future__ import annotations

from pathlib import Path

import pytest


def test_phase4_obsidian_adapter_produces_markdown_proposal_without_vault_access(tmp_path: Path):
    from integrations.obsidian import ObsidianAdapter

    adapter = ObsidianAdapter(vault_path=tmp_path / "vault")
    proposal = adapter.propose_write(
        title="Sleep note",
        body="# Sleep note\n\nKeep it local.",
        yaml_schema={"id": "KN-1", "domain": "body"},
        human="human",
        correlation_id="corr-1",
    )

    assert proposal["status"] == "pending_human_review"
    assert proposal["gateway"] == "knowledge"
    assert proposal["target"] == "markdown_vault"
    assert proposal["can_write"] is False
    assert not hasattr(adapter, "vault_path")


def test_phase4_llm_wiki_adapter_is_read_only_and_rejects_write_requests(tmp_path: Path):
    from integrations.llm_wiki import LlmWikiAdapter

    adapter = LlmWikiAdapter(exe_path=tmp_path / "llm_wiki.exe")

    assert adapter.health()["mode"] == "read_only"
    with pytest.raises(PermissionError, match="write"):
        adapter.write_knowledge("KN-1", "new content")


def test_phase4_feishu_adapter_requires_approval_and_is_idempotent():
    from integrations.feishu import FeishuAdapter

    adapter = FeishuAdapter()

    proposal = {
        "proposal_id": "PRO-1",
        "status": "approved",
        "title": "Publish Phase 4 proposal",
        "correlation_id": "corr-2",
        "idempotency_key": "idem-1",
    }
    task = adapter.submit_task(proposal)

    assert task["status"] == "submitted"
    assert task["proposal_id"] == "PRO-1"
    assert task["external_system"] == "feishu"


def test_phase4_obsidian_adapter_rejects_direct_vault_reads(tmp_path: Path):
    from integrations.obsidian import ObsidianAdapter

    adapter = ObsidianAdapter(vault_path=tmp_path / "vault")

    with pytest.raises(PermissionError, match="Knowledge Gateway"):
        adapter.read_local("05_Domains/Body/sleep.md")


def test_phase4_llm_wiki_adapter_rejects_private_paths(tmp_path: Path):
    from integrations.llm_wiki import LlmWikiAdapter

    adapter = LlmWikiAdapter(exe_path=tmp_path / "llm_wiki.exe")

    with pytest.raises(PermissionError, match="wiki"):
        adapter.read_file("../private.md")


def test_phase4_llm_wiki_adapter_rejects_all_file_operations(tmp_path: Path):
    from integrations.llm_wiki import LlmWikiAdapter

    adapter = LlmWikiAdapter(exe_path=tmp_path / "llm_wiki.exe")

    with pytest.raises(PermissionError, match="file operations"):
        adapter.read_file("wiki/allowed.md")


def test_phase4_llm_wiki_api_client_wraps_local_read_only_api():
    from integrations.llm_wiki_client import LlmWikiApiClient

    class Response:
        status = 200

        def read(self):
            return b'{"ok": true, "status": "running"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = LlmWikiApiClient(opener=lambda request, timeout: Response())

    assert client.health()["status"] == "running"
    with pytest.raises(ValueError, match="wiki"):
        client.file_content("current", "../private.md")
