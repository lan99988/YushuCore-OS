from __future__ import annotations

from pathlib import Path

from agents.information_pipeline import InformationPipeline
from capability_plugins import ActivationState, PluginRegistry, load_manifests
from capability_plugins.information import InformationPlugin
from capability_plugins.interest import InterestPlugin
from capability_plugins.life_admin import LifeAdminPlugin
from experience_layer import ExperienceRequest, ExperienceService
from experience_layer.flows.capture import CaptureFlow
from experience_layer.flows.explore import ExploreFlow
from information_system import InformationStore
from orchestration import (
    CapabilityPlanner,
    CapabilityRequest,
    Executor,
    FlowName,
    UserIntent,
)
from runtime_core import AgentDefinition, RuntimeKernel


ROOT = Path(__file__).resolve().parents[2]


def _runtime(tmp_path, domain_plugin_id, domain_plugin, permissions):
    manifests = tuple(
        manifest
        for manifest in load_manifests(ROOT / "capability_plugins" / "manifests")
        if manifest.plugin_id in {"information", domain_plugin_id}
    )
    registry = PluginRegistry.from_manifests(manifests)
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
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
            permissions=("ingest_information", *permissions),
            handler=lambda context: None,
        )
    )
    store = InformationStore(tmp_path / "information.db")
    store.init_schema()
    information_manifest = next(
        item for item in manifests if item.plugin_id == "information"
    )
    plugins = {
        "information": InformationPlugin(
            information_manifest,
            InformationPipeline(store),
        ),
        domain_plugin_id: domain_plugin,
    }
    service = ExperienceService(
        {
            FlowName.CAPTURE: CaptureFlow(
                CapabilityPlanner(
                    registry,
                    activate_on_demand=True,
                ),
                Executor(kernel, plugins),
                agent_id="experience_agent",
            )
        }
    )
    return service, registry, store


def test_passport_capture_activates_only_life_admin_and_returns_reviewable_reminder(
    tmp_path,
):
    life_admin = LifeAdminPlugin()
    service, registry, store = _runtime(
        tmp_path,
        "life_admin",
        life_admin,
        ("propose_reminder",),
    )
    assert registry.get("life_admin").activation_state is ActivationState.DORMANT

    response = service.handle(
        ExperienceRequest(
            text="护照明年 3 月到期。",
            correlation_id="corr-life-admin-e2e",
            context={"reference_date": "2026-09-27"},
        )
    )

    assert response.status == "completed", response
    assert registry.get("life_admin").activation_state is ActivationState.ACTIVE
    assert len(store.list_objects(status="inbox")) == 1
    assert [item.reason_code for item in response.confirmations] == [
        "life_admin_reminder_review"
    ]
    reminder = dict(response.confirmations[0].after)
    assert reminder == {
        "activated_subdomain": "identity_documents.passport",
        "due_at": "2027-03",
        "executed": False,
        "proposal_type": "reminder",
    }
    domains = life_admin.invoke("life_admin.domains", {}, {})
    assert domains["active_subdomains"] == ["identity_documents.passport"]
    assert all(
        item["activation_state"] == "dormant"
        for item in domains["domains"]
        if item["domain_id"] != "identity_documents"
    )
    assert any(
        event["action"] == "state_changed"
        and event["reason_code"] == "user_intent_requested_capability"
        for event in registry.audit_events
    )
    audit_text = (tmp_path / "runtime" / "audit.jsonl").read_text(encoding="utf-8")
    assert "护照明年" not in audit_text


def test_interest_capture_activates_interest_without_creating_task_or_kpi(tmp_path):
    interest = InterestPlugin()
    service, registry, store = _runtime(
        tmp_path,
        "interest",
        interest,
        ("propose_change",),
    )
    assert registry.get("interest").activation_state is ActivationState.DORMANT

    response = service.handle(
        ExperienceRequest(
            text="记一下，我最近对天文摄影很感兴趣。",
            correlation_id="corr-interest-e2e",
        )
    )

    assert response.status == "completed", response
    assert registry.get("interest").activation_state is ActivationState.ACTIVE
    assert len(store.list_objects(status="inbox")) == 1
    assert [item.reason_code for item in response.confirmations] == [
        "interest_topic_review"
    ]
    proposal = dict(response.confirmations[0].after)
    assert proposal["proposal_type"] == "interest_topic"
    assert proposal["title"] == "天文摄影"
    assert proposal["executed"] is False
    assert not ({"kpi", "streak", "target", "deadline", "task"} & set(proposal))
    assert all(
        diagnostic["capability"] != "task.create_proposal"
        for diagnostic in response.diagnostics
    )


def test_explore_reviews_approved_interest_events_through_read_only_plugin(tmp_path):
    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "interest"
    )
    registry = PluginRegistry.from_manifests((manifest,))
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
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
            risk_level="low",
            permissions=("read_interest",),
            handler=lambda context: None,
        )
    )
    interest = InterestPlugin(
        review_port=lambda interest_id: {
            "items": [
                {
                    "title": "天文摄影探索回顾",
                    "summary": "完成一次月面摄影尝试并记录曝光经验。",
                    "source": f"interest:{interest_id}:event-1",
                    "observed_at": "2026-09-20",
                    "confidence": 1.0,
                }
            ]
        }
    )
    response = ExperienceService(
        {
            FlowName.EXPLORE: ExploreFlow(
                CapabilityPlanner(
                    registry,
                    activate_on_demand=True,
                ),
                Executor(kernel, {"interest": interest}),
                agent_id="experience_agent",
            )
        }
    ).handle(
        ExperienceRequest(
            text="探索我过去的天文摄影兴趣历程。",
            correlation_id="corr-interest-review-e2e",
            context={
                "interest_id": "interest-astro-photo",
                "time_range": "2026-09-01/2026-09-27",
            },
        )
    )

    assert response.status == "completed", response
    assert registry.get("interest").activation_state is ActivationState.ACTIVE
    assert response.understood[0].title == "天文摄影探索回顾"
    assert response.understood[0].after["evidence"] == (
        "interest:interest-astro-photo:event-1"
    )
    assert response.suggestions == ()


def test_permission_denial_does_not_leave_interest_activated(tmp_path):
    manifest = next(
        item
        for item in load_manifests(ROOT / "capability_plugins" / "manifests")
        if item.plugin_id == "interest"
    )
    registry = PluginRegistry.from_manifests((manifest,))
    kernel = RuntimeKernel(
        gateway=object(),
        state_path=tmp_path / "runtime",
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
            risk_level="low",
            permissions=(),
            handler=lambda context: None,
        )
    )
    intent = UserIntent(
        flow=FlowName.CAPTURE,
        text="记一下，我最近对天文摄影很感兴趣。",
        confidence=1.0,
        evidence=("structured",),
        correlation_id="corr-interest-denied",
    )
    planning = CapabilityPlanner(
        registry,
        activate_on_demand=True,
    ).plan(
        intent,
        (
            CapabilityRequest(
                "interest-record",
                "interest.record_proposal",
                {"interest_id": "interest-astro-photo", "title": "天文摄影"},
            ),
        ),
    )

    result = Executor(kernel, {"interest": InterestPlugin()}).execute(
        planning.plan,
        agent_id="experience_agent",
        dry_run=False,
    )

    assert result.status == "blocked"
    assert result.steps[0].error_code == "agent_permission_denied"
    assert registry.get("interest").activation_state is ActivationState.DORMANT
