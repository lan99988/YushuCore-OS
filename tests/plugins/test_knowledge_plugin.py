from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_plugins import load_manifests
from knowledge_system.gateway import AgentPolicy, KnowledgeGateway, PermissionDenied, ReviewerPolicy
from knowledge_system.gateway.models import GatewayNode, QueryResponse


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"
EXPECTED_CAPABILITIES = (
    "knowledge.search",
    "knowledge.list",
    "knowledge.get",
    "knowledge.evidence_context",
    "knowledge.read_context",
    "knowledge.get_schema",
    "knowledge.health",
)
AGENT_ID = "review_agent"
CREDENTIAL = "review-agent-secret"


def _api():
    from capability_plugins.knowledge import KnowledgePlugin, KnowledgePluginError

    return KnowledgePlugin, KnowledgePluginError


def _manifest():
    return next(
        item
        for item in load_manifests(MANIFEST_DIR)
        if item.plugin_id == "knowledge"
    )


def _write_note(
    root: Path,
    relative: str,
    *,
    node_id: str,
    node_type: str = "knowledge",
    agent_access: str = AGENT_ID,
    body: str = "睡眠和恢复能够改善学习效率。",
) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {node_id}
type: {node_type}
title: {node_id} 标题
domain: [body]
layer: knowledge
source: [manual]
author: owner
created: 2026-08-04
updated: 2026-08-04
status: validated
confidence: 0.85
agent_access: [{agent_access}]
sensitivity: level_1
version: "1.0"
relations: []
---
# {node_id}

{body}
""",
        encoding="utf-8",
    )


def _gateway(tmp_path: Path) -> KnowledgeGateway:
    vault = tmp_path / "vault"
    _write_note(vault, "05_Domains/Body/allowed.md", node_id="KN-BODY-1")
    _write_note(
        vault,
        "05_Domains/Body/restricted.md",
        node_id="KN-BODY-PRIVATE",
        agent_access="other_agent",
    )
    _write_note(
        vault,
        "05_Domains/Body/experience.md",
        node_id="KN-EXP-1",
        node_type="experience",
    )
    _write_note(
        vault,
        "05_Domains/Body/principle.md",
        node_id="KN-PRINCIPLE-1",
        node_type="principle",
    )
    return KnowledgeGateway(
        vault,
        state_path=tmp_path / "state",
        policies={
            AGENT_ID: AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity="level_2",
            )
        },
        agent_credentials={AGENT_ID: CREDENTIAL},
        reviewers={"owner": ReviewerPolicy("owner-secret", can_approve_core=True)},
    )


def _gateway_node(*, domain=("body",)) -> GatewayNode:
    return GatewayNode(
        id="KN-BODY-1",
        type="knowledge",
        title="睡眠恢复",
        domain=domain,
        status="validated",
        confidence=0.85,
        sensitivity="level_1",
        path="05_Domains/Body/allowed.md",
        body="private query body",
        metadata={"private": "private metadata"},
    )


def test_knowledge_manifest_declares_gateway_read_only_capabilities():
    manifest = _manifest()

    assert manifest.domain == "knowledge"
    assert manifest.provides == EXPECTED_CAPABILITIES
    assert manifest.writes == ()
    assert manifest.permissions == ("read_knowledge",)
    assert set(manifest.capability_permissions) == set(EXPECTED_CAPABILITIES)
    assert all(
        manifest.capability_permissions[capability] == ("read_knowledge",)
        for capability in EXPECTED_CAPABILITIES
    )
    assert set(manifest.capability_effects) == set(EXPECTED_CAPABILITIES)
    assert set(manifest.capability_effects.values()) == {"read_only"}
    assert manifest.activation_mode == "always"


def test_search_uses_gateway_permissions_and_returns_safe_node_projection(tmp_path):
    KnowledgePlugin, _ = _api()
    gateway = _gateway(tmp_path)
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)

    result = plugin.invoke("knowledge.search", {"query": "睡眠"}, {})

    assert result["permission"] == "approved"
    assert [node["id"] for node in result["nodes"]] == [
        "KN-BODY-1",
        "KN-EXP-1",
        "KN-PRINCIPLE-1",
    ]
    assert result["denied_count"] == 1
    assert all("path" not in node and "metadata" not in node for node in result["nodes"])
    assert "睡眠和恢复" in result["nodes"][0]["content"]
    audit_path = tmp_path / "state" / "audit.jsonl"
    actions = [json.loads(line)["action"] for line in audit_path.read_text().splitlines()]
    assert actions == ["query_knowledge"]


def test_search_applies_time_range_and_projects_observed_date(tmp_path):
    KnowledgePlugin, _ = _api()
    plugin = KnowledgePlugin(
        _gateway(tmp_path), agent_id=AGENT_ID, credential=CREDENTIAL
    )

    included = plugin.invoke(
        "knowledge.search",
        {"query": "睡眠", "time_range": "2026-08-01/2026-08-31"},
        {},
    )
    excluded = plugin.invoke(
        "knowledge.search",
        {"query": "睡眠", "time_range": "2026-09-01/2026-09-30"},
        {},
    )

    assert included["nodes"][0]["observed_at"] == "2026-08-04"
    assert excluded["nodes"] == []


def test_get_filters_only_gateway_authorized_nodes_by_exact_id(tmp_path):
    KnowledgePlugin, KnowledgePluginError = _api()
    gateway = _gateway(tmp_path)
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)

    result = plugin.invoke("knowledge.get", {"node_id": "KN-BODY-1"}, {})

    assert result["id"] == "KN-BODY-1"
    assert "content" in result
    assert "path" not in result
    audit_path = tmp_path / "state" / "audit.jsonl"
    assert [json.loads(line)["action"] for line in audit_path.read_text().splitlines()] == [
        "query_knowledge"
    ]

    with pytest.raises(KnowledgePluginError) as denied:
        plugin.invoke("knowledge.get", {"node_id": "KN-BODY-PRIVATE"}, {})
    assert denied.value.code == "node_not_found"
    assert "KN-BODY-PRIVATE" not in str(denied.value)


def test_evidence_context_uses_gateway_grouping_without_writes(tmp_path):
    KnowledgePlugin, _ = _api()
    gateway = _gateway(tmp_path)
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)

    result = plugin.invoke(
        "knowledge.evidence_context", {"task": "恢复"}, {"request_id": "test"}
    )

    assert [node["id"] for node in result["knowledge"]] == ["KN-BODY-1"]
    assert [node["id"] for node in result["experience"]] == ["KN-EXP-1"]
    assert [node["id"] for node in result["principles"]] == ["KN-PRINCIPLE-1"]
    assert all("path" not in node for group in result.values() for node in group)
    assert plugin.manifest.writes == ()


def test_legacy_read_context_alias_uses_the_injected_gateway(tmp_path):
    KnowledgePlugin, _ = _api()
    gateway = _gateway(tmp_path)
    calls = []
    original_get_context = gateway.get_context

    def get_context(task, *, agent_id, credential):
        calls.append((task, agent_id, credential))
        return original_get_context(task, agent_id=agent_id, credential=credential)

    gateway.get_context = get_context
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)

    result = plugin.invoke("knowledge.read_context", {"task": "恢复"}, {})

    assert calls == [("恢复", AGENT_ID, CREDENTIAL)]
    assert [node["id"] for node in result["knowledge"]] == ["KN-BODY-1"]
    assert [node["id"] for node in result["experience"]] == ["KN-EXP-1"]
    assert [node["id"] for node in result["principles"]] == ["KN-PRINCIPLE-1"]


def test_legacy_get_schema_fails_closed_without_gateway_schema_api():
    KnowledgePlugin, KnowledgePluginError = _api()

    class GatewayWithoutSchema:
        def __init__(self):
            self.calls = []

        def query_knowledge(self, *args, **kwargs):
            self.calls.append(("query_knowledge", args, kwargs))

        def get_context(self, *args, **kwargs):
            self.calls.append(("get_context", args, kwargs))

    gateway = GatewayWithoutSchema()
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)

    with pytest.raises(KnowledgePluginError) as error:
        plugin.invoke("knowledge.get_schema", {"node_id": "KN-BODY-1"}, {})

    assert error.value.code == "schema_unavailable"
    assert error.value.__cause__ is None
    assert gateway.calls == []


def test_legacy_health_only_reports_adapter_availability():
    KnowledgePlugin, _ = _api()

    class SensitiveGateway:
        def query_knowledge(self, *_args, **_kwargs):
            raise AssertionError("health must not read knowledge")

        def get_context(self, *_args, **_kwargs):
            raise AssertionError("health must not read context")

    plugin = KnowledgePlugin(
        SensitiveGateway(), agent_id=AGENT_ID, credential=CREDENTIAL
    )

    result = plugin.invoke("knowledge.health", {}, {})

    assert result == {"status": "available"}
    assert "content" not in result
    assert "vault" not in result


def test_gateway_exceptions_are_redacted_without_exception_chaining():
    KnowledgePlugin, KnowledgePluginError = _api()

    class BrokenGateway:
        def query_knowledge(self, *_args, **_kwargs):
            raise RuntimeError("private vault body")

        def get_context(self, *_args, **_kwargs):
            raise PermissionDenied("sensitive policy detail")

    plugin = KnowledgePlugin(
        BrokenGateway(), agent_id=AGENT_ID, credential=CREDENTIAL
    )
    with pytest.raises(KnowledgePluginError) as search_error:
        plugin.invoke("knowledge.search", {"query": "sleep"}, {})
    assert search_error.value.code == "gateway_unavailable"
    assert "private vault body" not in str(search_error.value)
    assert search_error.value.__cause__ is None

    with pytest.raises(KnowledgePluginError) as context_error:
        plugin.invoke("knowledge.evidence_context", {"task": "sleep"}, {})
    assert context_error.value.code == "permission_denied"
    assert "sensitive policy detail" not in str(context_error.value)
    assert context_error.value.__cause__ is None


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        ("knowledge.search", {"query": "private query"}),
        ("knowledge.get", {"node_id": "KN-BODY-1"}),
    ],
)
def test_query_capabilities_redact_permission_denial(capability, payload):
    KnowledgePlugin, KnowledgePluginError = _api()

    class DeniedGateway:
        def query_knowledge(self, *_args, **_kwargs):
            raise PermissionDenied("private query policy sentinel")

        def get_context(self, *_args, **_kwargs):
            raise AssertionError("query capability must not call get_context")

    plugin = KnowledgePlugin(
        DeniedGateway(), agent_id=AGENT_ID, credential=CREDENTIAL
    )

    with pytest.raises(KnowledgePluginError) as error:
        plugin.invoke(capability, payload, {})

    assert error.value.code == "permission_denied"
    assert "private query policy sentinel" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        ("knowledge.search", {"query": "sleep"}),
        ("knowledge.get", {"node_id": "KN-BODY-1"}),
    ],
)
@pytest.mark.parametrize(
    ("malformation", "expected_code"),
    [
        ("wrong_response_type", "invalid_gateway_response"),
        ("nodes_not_list", "invalid_gateway_response"),
        ("wrong_node_type", "invalid_gateway_response"),
        ("bad_node_domain", "invalid_gateway_response"),
        ("bad_permission_type", "invalid_gateway_response"),
        ("bad_count_type", "invalid_gateway_response"),
        ("denied_with_nodes", "permission_denied"),
    ],
)
def test_query_capabilities_fail_closed_on_malformed_gateway_response(
    capability, payload, malformation, expected_code
):
    KnowledgePlugin, KnowledgePluginError = _api()
    if malformation == "wrong_response_type":
        response = {"nodes": ["private query sentinel"]}
    elif malformation == "nodes_not_list":
        response = QueryResponse(None, "approved", 0, 0)
    elif malformation == "wrong_node_type":
        response = QueryResponse(["private query sentinel"], "approved", 0, 0)
    elif malformation == "bad_node_domain":
        response = QueryResponse(
            [_gateway_node(domain=None)], "approved", 0, 0
        )
    elif malformation == "bad_permission_type":
        response = QueryResponse([_gateway_node()], 1, 0, 0)
    elif malformation == "bad_count_type":
        response = QueryResponse([_gateway_node()], "approved", True, 0)
    else:
        response = QueryResponse([_gateway_node()], "denied", 0, 0)

    class MalformedGateway:
        def query_knowledge(self, *_args, **_kwargs):
            return response

        def get_context(self, *_args, **_kwargs):
            raise AssertionError("query capability must not call get_context")

    plugin = KnowledgePlugin(
        MalformedGateway(), agent_id=AGENT_ID, credential=CREDENTIAL
    )

    with pytest.raises(KnowledgePluginError) as error:
        plugin.invoke(capability, payload, {})

    assert error.value.code == expected_code
    assert "private query sentinel" not in str(error.value)
    assert error.value.__cause__ is None


def test_knowledge_plugin_validates_inputs_and_unknown_capability():
    KnowledgePlugin, KnowledgePluginError = _api()

    class RecordingGateway:
        def __init__(self):
            self.calls = []

        def query_knowledge(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return type(
                "Query",
                (),
                {"nodes": [], "permission": "approved", "denied_count": 0, "invalid_count": 0},
            )()

        def get_context(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return type(
                "Context", (), {"knowledge": [], "experience": [], "principles": []}
            )()

    gateway = RecordingGateway()
    plugin = KnowledgePlugin(gateway, agent_id=AGENT_ID, credential=CREDENTIAL)
    with pytest.raises(KnowledgePluginError) as missing:
        plugin.invoke("knowledge.search", {}, {})
    assert missing.value.code == "invalid_query"
    with pytest.raises(KnowledgePluginError) as invalid:
        plugin.invoke("knowledge.get", {"node_id": "  "}, {})
    assert invalid.value.code == "invalid_node_id"
    with pytest.raises(KnowledgePluginError) as unknown:
        plugin.invoke("knowledge.write", {}, {})
    assert unknown.value.code == "unsupported_capability"
    assert gateway.calls == []
