from __future__ import annotations

from pathlib import Path

from capability_plugins import (
    ActivationState,
    PluginLifecycle,
    PluginRegistry,
    load_manifests,
)
from capability_plugins.knowledge import KnowledgePlugin
from capability_plugins.learning import LearningPlugin
from capability_plugins.project import ProjectPlugin
from experience_layer import ExperienceRequest
from experience_layer.flows.explore import ExploreFlow
from experience_layer.flows.review import ReviewFlow
from information_system.projects import ProjectRecord, ProjectResolver
from knowledge_system.gateway.models import ContextResponse, GatewayNode, QueryResponse
from orchestration import CapabilityPlanner, Executor, FlowName, UserIntent
from runtime_core import AgentDefinition, RuntimeKernel


ROOT = Path(__file__).resolve().parents[2]


def _manifest_registry(*plugin_ids: str) -> PluginRegistry:
    manifests = tuple(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id in set(plugin_ids)
    )
    assert {item.plugin_id for item in manifests} == set(plugin_ids)
    registry = PluginRegistry.from_manifests(manifests)
    lifecycle = PluginLifecycle(registry)
    for plugin_id in plugin_ids:
        if registry.get(plugin_id).activation_state is ActivationState.DORMANT:
            lifecycle.transition(
                plugin_id,
                activation_state=ActivationState.ACTIVE,
                actor="test",
                reason="e2e_fixture",
            )
    return registry


def _kernel(tmp_path: Path, registry: PluginRegistry) -> RuntimeKernel:
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path,
        local_model="local-test",
        cloud_model="cloud-test",
        plugin_registry=registry,
    )
    kernel.register_agent(
        AgentDefinition(
            agent_id="experience_agent",
            name="Experience Agent",
            domain="experience",
            autonomy_level=2,
            risk_level="medium",
            permissions=("read_knowledge", "read_project"),
            handler=lambda context: None,
        )
    )
    return kernel


class ApprovedKnowledgeSource:
    def query_knowledge(self, query, *, agent_id, credential):
        del query, agent_id, credential
        return QueryResponse(
            nodes=[
                GatewayNode(
                    id="KN-HABIT-1",
                    type="knowledge",
                    title="下午启动延迟",
                    domain=("productivity",),
                    status="validated",
                    confidence=0.81,
                    sensitivity="level_0",
                    path="hidden.md",
                    body="过去四周下午任务平均更晚开始。",
                    metadata={"updated": "2026-09-26"},
                )
            ],
            permission="approved",
            denied_count=0,
            invalid_count=0,
        )

    def get_context(self, task, *, agent_id, credential):
        del task, agent_id, credential
        return ContextResponse(knowledge=[], experience=[], principles=[])


def test_explore_reads_real_knowledge_plugin_through_governed_runtime(tmp_path):
    registry = _manifest_registry("knowledge")
    plugin = KnowledgePlugin(
        ApprovedKnowledgeSource(),
        agent_id="experience_agent",
        credential="test-credential",
    )
    flow = ExploreFlow(
        CapabilityPlanner(registry),
        Executor(_kernel(tmp_path / "explore", registry), {"knowledge": plugin}),
        agent_id="experience_agent",
    )
    request = ExperienceRequest(
        text="最近为什么总拖延？",
        correlation_id="corr-e2e-explore",
        structured_flow=FlowName.EXPLORE,
        context={"time_range": "2026-09-01/2026-09-27"},
    )
    intent = UserIntent(
        flow=FlowName.EXPLORE,
        text=request.text,
        confidence=1.0,
        evidence=("structured",),
        correlation_id=request.correlation_id,
    )

    response = flow.run(request, intent)

    assert response.status == "completed", response
    assert response.understood[0].after["evidence"] == "KN-HABIT-1"
    assert response.understood[0].after["confidence"] == 0.81


def test_review_reads_real_project_and_learning_plugins_through_runtime(tmp_path):
    registry = _manifest_registry("project", "learning")
    resolver = ProjectResolver(projects=(ProjectRecord(name="Personal OS"),))
    project = ProjectPlugin(
        project_resolver=resolver,
        context_provider=lambda record: {
            "behaviors": [{"title": f"检查 {record.name}"}],
            "results": [{"title": "识别一个风险"}],
        },
    )
    learning = LearningPlugin(
        delegates={"learning.progress": lambda payload: {"completed": 4, "target": 8}}
    )
    project.manifest = registry.get("project")
    learning.manifest = registry.get("learning")
    flow = ReviewFlow(
        CapabilityPlanner(registry),
        Executor(
            _kernel(tmp_path / "review", registry),
            {"project": project, "learning": learning},
        ),
        agent_id="experience_agent",
    )
    request = ExperienceRequest(
        text="复盘本周",
        correlation_id="corr-e2e-review",
        structured_flow=FlowName.REVIEW,
        context={"period": "2026-W39", "project_id": "Personal OS"},
    )
    intent = UserIntent(
        flow=FlowName.REVIEW,
        text=request.text,
        confidence=1.0,
        evidence=("structured",),
        correlation_id=request.correlation_id,
    )

    response = flow.run(request, intent)

    assert response.status == "completed", response
    assert [item.reason_code for item in response.understood] == [
        "behavior_observed",
        "result_observed",
        "result_observed",
    ]
    assert response.understood[-1].after["ratio"] == 0.5
