from __future__ import annotations

from pathlib import Path

from knowledge_system.gateway import AgentPolicy, KnowledgeGateway, ReviewerPolicy
from runtime_core import RuntimeKernel
from runtime_core.config import load_agent_definitions


BODY_CREDENTIAL = "body-secret"
STUDY_CREDENTIAL = "study-secret"
OWNER_CREDENTIAL = "owner-secret"


def _write_note(root: Path, relative: str, *, node_id: str, domain: str, agent: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {node_id}
type: knowledge
title: {node_id}
domain: {domain}
layer: knowledge
source: manual
author: owner
created: 2026-08-04
updated: 2026-08-04
status: validated
confidence: 0.85
agent_access:
  - {agent}
sensitivity: level_1
version: "1.0"
relations: []
---
# {node_id}

{domain} knowledge
""",
        encoding="utf-8",
    )


def _gateway(tmp_path: Path) -> KnowledgeGateway:
    vault = tmp_path / "vault"
    _write_note(
        vault,
        "05_Domains/Knowledge/concept.md",
        node_id="KN-KNOW-1",
        domain="knowledge",
        agent="knowledge_agent",
    )
    _write_note(vault, "05_Domains/Body/sleep.md", node_id="KN-BODY-1", domain="body", agent="body_agent")
    _write_note(
        vault,
        "05_Domains/Study/learning.md",
        node_id="KN-STUDY-1",
        domain="study",
        agent="study_agent",
    )
    return KnowledgeGateway(
        vault,
        state_path=tmp_path / "gateway_state",
        policies={
            "knowledge_agent": AgentPolicy(
                allowed_folders=("05_Domains",),
                allowed_domains=("body", "study", "project", "knowledge"),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
            "body_agent": AgentPolicy(
                allowed_folders=("05_Domains/Body",),
                allowed_domains=("body",),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
            "study_agent": AgentPolicy(
                allowed_folders=("05_Domains/Study",),
                allowed_domains=("study",),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
            "project_agent": AgentPolicy(
                allowed_folders=("05_Domains/Projects",),
                allowed_domains=("project",),
                max_sensitivity="level_2",
                max_proposal_sensitivity="level_2",
            ),
        },
        agent_credentials={
            "knowledge_agent": "knowledge-secret",
            "body_agent": BODY_CREDENTIAL,
            "study_agent": STUDY_CREDENTIAL,
            "project_agent": "project-secret",
        },
        reviewers={"owner": ReviewerPolicy(credential=OWNER_CREDENTIAL, can_approve_core=True)},
    )


def test_phase3_registry_yaml_loads_four_agents():
    handlers = {
        "knowledge_agent_handler": lambda context: None,
        "body_agent_handler": lambda context: None,
        "study_agent_handler": lambda context: None,
        "project_agent_handler": lambda context: None,
    }
    definitions = load_agent_definitions("agents/registry.yaml", handlers)

    assert [definition.agent_id for definition in definitions] == [
        "knowledge_agent",
        "body_agent",
        "study_agent",
        "project_agent",
    ]
    assert [definition.domain for definition in definitions] == [
        "knowledge",
        "body",
        "study",
        "project",
    ]


def test_phase3_agent_sdk_builds_standard_response():
    from agents.sdk import AgentResponse, AgentSDK, SkillSpec, make_agent_definition

    skill = SkillSpec(
        skill_id="skill_summary",
        name="Summary Skill",
        domain="knowledge",
        required_permissions=("read_knowledge",),
        risk_level="low",
    )
    response = AgentResponse(
        summary="ok",
        findings=["a"],
        proposals=[{"target_id": "KN-1"}],
        next_actions=["review"],
    )
    definition = make_agent_definition(
        agent_id="knowledge_agent",
        name="Knowledge Agent",
        domain="knowledge",
        autonomy_level=2,
        risk_level="medium",
        permissions=("execute", "read_knowledge"),
        handler=lambda context: response,
    )
    sdk = AgentSDK(agent_id=definition.agent_id, domain=definition.domain, skills=(skill,))

    assert definition.agent_id == "knowledge_agent"
    assert sdk.response(summary="ok").summary == "ok"
    assert sdk.skills[0].skill_id == "skill_summary"


def test_phase3_agents_execute_through_runtime(tmp_path: Path):
    from agents import phase3_handler_map
    from agents.registry import load_phase3_agent_definitions
    from agents.sdk import AgentResponse

    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    definitions = load_phase3_agent_definitions("agents/registry.yaml", handlers=phase3_handler_map())
    for definition in definitions:
        kernel.register_agent(definition)
        kernel.activate_agent(definition.agent_id)

    credentials = {
        "knowledge_agent": "knowledge-secret",
        "body_agent": BODY_CREDENTIAL,
        "study_agent": STUDY_CREDENTIAL,
        "project_agent": "project-secret",
    }

    for agent_id, credential in credentials.items():
        result = kernel.execute(agent_id, credential=credential, task=f"{agent_id} task")

        assert isinstance(result.output, AgentResponse)
        assert result.output.summary
        assert kernel.memory.size(agent_id) == 1


def test_phase3_sdk_submits_knowledge_proposal_through_runtime(tmp_path: Path):
    from agents import phase3_handler_map
    from agents.registry import load_phase3_agent_definitions
    from agents.sdk import AgentSDK

    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    for definition in load_phase3_agent_definitions(
        "agents/registry.yaml",
        handlers=phase3_handler_map(),
    ):
        kernel.register_agent(definition)
        kernel.activate_agent(definition.agent_id)

    target = tmp_path / "vault/05_Domains/Knowledge/concept.md"
    before = target.read_text(encoding="utf-8")
    sdk = AgentSDK(agent_id="knowledge_agent", domain="knowledge")

    proposal = sdk.submit_proposal(
        runtime=kernel,
        credential="knowledge-secret",
        target_id="KN-KNOW-1",
        old="knowledge knowledge",
        new="knowledge should remain human reviewed",
        reason="Convert finding into a reviewed knowledge proposal.",
        confidence=0.82,
        risk="medium",
    )

    after = target.read_text(encoding="utf-8")
    assert proposal.status == "pending"
    assert proposal.agent == "knowledge_agent"
    assert before == after
    assert "knowledge should remain human reviewed" not in after


def test_knowledge_agent_generates_reviewable_candidate_proposals(tmp_path: Path):
    from agents import phase3_handler_map
    from agents.registry import load_phase3_agent_definitions

    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    for definition in load_phase3_agent_definitions(
        "agents/registry.yaml",
        handlers=phase3_handler_map(),
    ):
        kernel.register_agent(definition)
        kernel.activate_agent(definition.agent_id)

    result = kernel.execute(
        "knowledge_agent",
        credential="knowledge-secret",
        task="knowledge",
    )

    proposal = result.output.proposals[0]
    assert proposal["status"] == "draft"
    assert proposal["target_id"] == "KN-KNOW-1"
    assert proposal["old"] == "knowledge knowledge"
    assert proposal["new"] == "knowledge knowledge\n\nReview note: keep this change human-approved."
    assert proposal["confidence"] == 0.7
    assert proposal["risk"] == "medium"


def test_knowledge_analyzer_builds_structured_findings(tmp_path: Path):
    from agents import phase3_handler_map
    from agents.knowledge_analyzer import analyze_context
    from agents.registry import load_phase3_agent_definitions

    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    for definition in load_phase3_agent_definitions(
        "agents/registry.yaml",
        handlers=phase3_handler_map(),
    ):
        kernel.register_agent(definition)
        kernel.activate_agent(definition.agent_id)

    context = kernel.get_context(
        "knowledge_agent",
        credential="knowledge-secret",
        task="knowledge",
    )
    findings = analyze_context(context)

    assert findings[0].node_id == "KN-KNOW-1"
    assert findings[0].domain == "knowledge"
    assert findings[0].summary == "knowledge knowledge"
    assert findings[0].source_path == "05_Domains/Knowledge/concept.md"


def test_knowledge_reviewer_converts_findings_to_candidate_proposals(tmp_path: Path):
    from agents import phase3_handler_map
    from agents.knowledge_analyzer import analyze_context
    from agents.knowledge_reviewer import review_findings
    from agents.registry import load_phase3_agent_definitions

    gateway = _gateway(tmp_path)
    kernel = RuntimeKernel(
        gateway=gateway,
        state_path=tmp_path / "runtime_state",
        local_model="qwen3:8b",
        cloud_model="deepseek-reasoner",
    )
    for definition in load_phase3_agent_definitions(
        "agents/registry.yaml",
        handlers=phase3_handler_map(),
    ):
        kernel.register_agent(definition)
        kernel.activate_agent(definition.agent_id)

    context = kernel.get_context(
        "knowledge_agent",
        credential="knowledge-secret",
        task="knowledge",
    )
    proposals = review_findings(analyze_context(context))

    assert proposals[0]["target_id"] == "KN-KNOW-1"
    assert proposals[0]["status"] == "draft"
    assert proposals[0]["reason"] == "Convert finding into a reviewed knowledge proposal."
