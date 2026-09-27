from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from capability_plugins import PluginRegistry
from runtime_core.access import AccessRequestDenied, AccessRequestStore
from runtime_core.action_policy import ActionPolicy
from runtime_core.approval import ApprovalEngine
from runtime_core.audit import AuditLogger, AuditRecord
from runtime_core.collaboration import AgentEventRelay
from runtime_core.config import AgentHandlerMap, load_agent_definitions
from runtime_core.context import ContextManager
from runtime_core.events import EventBus
from runtime_core.gateway_client import KnowledgeGatewayClient
from runtime_core.logger import RuntimeLogger
from runtime_core.memory import MemoryManager
from runtime_core.models import ActionAuthority, AgentDefinition, AgentGovernance, AgentRequest, AgentResult, PlannedAction, PolicyDecision, RuntimeContext, RuntimeResult
from runtime_core.permissions import PermissionManager
from runtime_core.policy import RuntimePolicy
from runtime_core.registry import AgentRegistry
from runtime_core.router import ModelRouter
from runtime_core.scheduler import AgentScheduler
from runtime_core.tools import ToolManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SENSITIVITY_RANK = {
    "level_0": 0,
    "level_1": 1,
    "level_2": 2,
    "level_3": 3,
    "level_4": 4,
}


def _max_context_sensitivity(knowledge_context) -> str:
    max_level = "level_0"
    for node in (
        list(knowledge_context.knowledge)
        + list(knowledge_context.experience)
        + list(knowledge_context.principles)
    ):
        sensitivity = getattr(node, "sensitivity", "level_0")
        if _SENSITIVITY_RANK.get(sensitivity, 0) > _SENSITIVITY_RANK[max_level]:
            max_level = sensitivity
    return max_level


def _access_grant_denied_event(
    agent_id: str,
    request,
    reason: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    return {
        "event": "access_grant_denied",
        "agent_id": agent_id,
        "request_id": request.request_id,
        "resource": request.resource,
        "sensitivity": request.sensitivity,
        "reason": reason,
        "timestamp": _now(),
        **_correlation_fields(correlation_id),
    }


def _access_request_denied_event(
    agent_id: str,
    resource: str,
    error_type: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    return {
        "event": "access_request_denied",
        "agent_id": agent_id,
        "resource": resource,
        "error_type": error_type,
        "timestamp": _now(),
        **_correlation_fields(correlation_id),
    }


def _proposal_denied_event(
    action: str,
    *,
    agent_id: str | None,
    proposal_id: str | None,
    target_id: str | None,
    reviewer: str | None,
    error_type: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    event = {
        "event": "proposal_denied",
        "action": action,
        "error_type": error_type,
        "timestamp": _now(),
    }
    if agent_id is not None:
        event["agent_id"] = agent_id
    if proposal_id is not None:
        event["proposal_id"] = proposal_id
    if target_id is not None:
        event["target_id"] = target_id
    if reviewer is not None:
        event["reviewer"] = reviewer
    event.update(_correlation_fields(correlation_id))
    return event


def _correlation_fields(correlation_id: str) -> dict[str, str]:
    return {"correlation_id": correlation_id or uuid4().hex}


def _detail_fields(details: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in details)


def _error_type(exc: Exception) -> str:
    return exc.__class__.__name__


class RuntimeKernel:
    def __init__(
        self,
        *,
        gateway: Any | None = None,
        gateway_client: KnowledgeGatewayClient | None = None,
        state_path: str | Path,
        local_model: str,
        cloud_model: str,
        model_router: ModelRouter | None = None,
        default_network_mode: str = "OFF",
        retry_max_attempts: int = 1,
        action_policy: ActionPolicy | None = None,
        audit_logger: AuditLogger | None = None,
        plugin_registry: PluginRegistry | None = None,
    ) -> None:
        if default_network_mode not in {"OFF", "ASSIST", "SYNC"}:
            raise ValueError("default_network_mode must be OFF, ASSIST, or SYNC")
        if retry_max_attempts < 1:
            raise ValueError("retry_max_attempts must be at least 1")
        if gateway is None and gateway_client is None:
            raise ValueError("gateway or gateway_client is required")
        if gateway is not None and gateway_client is not None:
            raise ValueError("gateway and gateway_client cannot both be provided")
        self.default_network_mode = default_network_mode
        self.retry_max_attempts = retry_max_attempts
        self.gateway_client = gateway_client or KnowledgeGatewayClient(gateway)
        self.registry = AgentRegistry()
        self.scheduler = AgentScheduler()
        self.permissions = PermissionManager()
        self.access_requests = AccessRequestStore(state_path)
        self.memory = MemoryManager(state_path)
        self.events = EventBus()
        self.logger = RuntimeLogger(state_path)
        self.events.subscribe(self.logger.write)
        permission_config = Path(__file__).resolve().parents[1] / "config" / "permission.yaml"
        self.action_policy = action_policy or ActionPolicy.from_file(permission_config)
        self.audit = audit_logger or AuditLogger(state_path)
        self.plugin_registry = plugin_registry
        self.collaboration = AgentEventRelay(self.events)
        self.model_router = model_router or ModelRouter(
            local_model=local_model,
            cloud_model=cloud_model,
        )
        self.context = ContextManager(self.gateway_client, self.permissions)
        self.approvals = ApprovalEngine(self.gateway_client, self.permissions)
        self.tools = ToolManager(self.permissions, self.events)

    @classmethod
    def from_policy(
        cls,
        *,
        gateway: Any | None = None,
        gateway_client: KnowledgeGatewayClient | None = None,
        state_path: str | Path,
        policy: RuntimePolicy,
    ) -> "RuntimeKernel":
        return cls(
            gateway=gateway,
            gateway_client=gateway_client,
            state_path=state_path,
            local_model=policy.local_model,
            cloud_model=policy.cloud_model,
            model_router=policy.model_router(),
            default_network_mode=policy.network_mode,
            retry_max_attempts=policy.retry.max_attempts,
        )

    def register_agent(self, definition: AgentDefinition) -> None:
        self.registry.register(definition)
        self.scheduler.register(definition.agent_id)

    def authorize_action(
        self,
        agent_id: str,
        action: PlannedAction,
        *,
        correlation_id: str,
        prohibited: bool = False,
        flow: str | None = None,
    ) -> PolicyDecision:
        """Evaluate and audit one new planned-action execution boundary."""
        correlation_id = correlation_id or uuid4().hex
        agent = self.registry.get(agent_id)
        if self.plugin_registry is None:
            raise RuntimeError("plugin_registry_required")
        manifest = self.plugin_registry.by_capability(action.capability)
        if manifest.plugin_id != action.plugin_id:
            raise ValueError("planned action plugin does not match registered provider")

        risk_rank = {"low": 0, "medium": 1, "high": 2}
        if action.risk in risk_rank:
            trusted_risk = max(
                (action.risk, manifest.risk_level.value),
                key=risk_rank.__getitem__,
            )
        else:
            trusted_risk = action.risk
        capability_effect = manifest.capability_effects.get(action.capability)
        trusted_permissions = manifest.capability_permissions.get(
            action.capability, manifest.permissions
        )
        if capability_effect == "read_only":
            trusted_authority = ActionAuthority.OBSERVE
            trusted_external_effect = action.external_effect
            trusted_reversible = True
        elif capability_effect in {"proposal", "internal_write"}:
            trusted_authority = ActionAuthority.AUTONOMOUS
            trusted_external_effect = action.external_effect
            trusted_reversible = action.reversible
        elif capability_effect == "external_write":
            trusted_authority = ActionAuthority.APPROVAL_REQUIRED
            trusted_external_effect = True
            trusted_reversible = False
        else:
            trusted_authority = action.authority
            trusted_external_effect = action.external_effect or bool(manifest.writes)
            trusted_reversible = action.reversible
        trusted_action = replace(
            action,
            risk=trusted_risk,
            authority=trusted_authority,
            reversible=trusted_reversible,
            external_effect=trusted_external_effect,
            required_permissions=trusted_permissions,
            operation=action.capability,
            resource=f"plugin:{manifest.plugin_id}",
        )
        decision = self.action_policy.evaluate(
            trusted_action,
            plugin_permissions=manifest.permissions,
            agent_permissions=agent.permissions,
            agent_autonomy_level=agent.autonomy_level,
            known_capabilities=manifest.provides,
            prohibited=prohibited,
        )
        if decision.allowed:
            result = "allowed"
        elif decision.approval_required:
            result = "pending_approval"
        else:
            result = "suggested"
        self.audit.write(
            AuditRecord(
                actor=f"agent:{agent.agent_id}",
                operation=trusted_action.capability,
                resource=trusted_action.resource,
                decision=decision.effective_authority.value,
                reason_code=decision.reason_code,
                correlation_id=correlation_id,
                timestamp=_now(),
                result=result,
                plugin_id=trusted_action.plugin_id,
                capability=trusted_action.capability,
                payload_digest=trusted_action.payload_digest,
            )
        )
        event_name = (
            "policy_allowed"
            if decision.allowed
            else "approval_required"
            if decision.approval_required
            else "policy_blocked"
        )
        self.events.publish(
            {
                "event": event_name,
                "flow": flow or "unresolved",
                "agent_id": agent.agent_id,
                "plugin_id": trusted_action.plugin_id,
                "capability": trusted_action.capability,
                "step_id": trusted_action.action_id,
                "reason_code": decision.reason_code,
                "correlation_id": correlation_id,
                "timestamp": _now(),
            }
        )
        return decision

    def load_agents_from_file(self, path: str | Path, *, handlers: AgentHandlerMap) -> None:
        for definition in load_agent_definitions(path, handlers):
            self.register_agent(definition)

    def activate_agent(self, agent_id: str, *, correlation_id: str = "") -> None:
        agent = self.registry.get(agent_id)
        self.scheduler.activate(agent.agent_id)
        self.events.publish(
            {
                "event": "agent_activated",
                "agent_id": agent.agent_id,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )

    def deactivate_agent(self, agent_id: str, *, correlation_id: str = "") -> None:
        agent = self.registry.get(agent_id)
        self.scheduler.deactivate(agent.agent_id)
        self.events.publish(
            {
                "event": "agent_deactivated",
                "agent_id": agent.agent_id,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )

    def execute(
        self,
        agent_id: str,
        *,
        credential: str,
        task: str,
        complexity: str = "standard",
        network_mode: str | None = None,
        correlation_id: str = "",
    ) -> RuntimeResult:
        correlation_id = correlation_id or uuid4().hex
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        self.permissions.require(agent, "execute")
        knowledge_context = self.context.build(agent, credential=credential, task=task)
        selected_network_mode = network_mode or self.default_network_mode
        max_context_sensitivity = _max_context_sensitivity(knowledge_context)
        route = self.model_router.select(
            complexity=complexity,
            network_mode=selected_network_mode,
            max_context_sensitivity=max_context_sensitivity,
        )
        self.events.publish(
            {
                "event": "model_route_selected",
                "agent_id": agent.agent_id,
                "provider": route.provider,
                "reason": route.reason,
                "network_mode": selected_network_mode,
                "complexity": complexity,
                "max_context_sensitivity": max_context_sensitivity,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        output = None
        last_error: Exception | None = None
        attempt = 0
        for attempt in range(1, self.retry_max_attempts + 1):
            self.events.publish(
                {
                    "event": "agent_started",
                    "agent_id": agent.agent_id,
                    "task": task,
                    "attempt": attempt,
                    "timestamp": _now(),
                    **_correlation_fields(correlation_id),
                }
            )
            runtime_context = RuntimeContext(
                agent_id=agent.agent_id,
                task=task,
                model=route,
                knowledge=knowledge_context.knowledge,
                experience=knowledge_context.experience,
                principles=knowledge_context.principles,
                memory=self.memory,
                tools=self.tools.bind(agent),
                approvals=self.approvals,
                collaboration=self.collaboration,
                correlation_id=correlation_id,
            )
            try:
                output = agent.handler(runtime_context)
                if is_dataclass(output) and hasattr(output, "governance"):
                    output = replace(
                        output,
                        governance=AgentGovernance(
                            agent_id=agent.agent_id,
                            permissions=tuple(agent.permissions),
                            can_access=(f"knowledge_gateway:{agent.domain}", "runtime_context"),
                            cannot_access=("vault_filesystem", "external_apis", "personal_memory:11_Self_Model"),
                            tools_called=tuple(runtime_context.tools.calls),
                            audit_recorded=True,
                        ),
                    )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < self.retry_max_attempts:
                    self.events.publish(
                        {
                            "event": "agent_retry",
                            "agent_id": agent.agent_id,
                            "task": task,
                            "attempt": attempt,
                            "error_type": _error_type(exc),
                            "timestamp": _now(),
                            **_correlation_fields(correlation_id),
                        }
                    )
                    continue
                self.events.publish(
                    {
                        "event": "agent_failed",
                        "agent_id": agent.agent_id,
                        "task": task,
                        "attempt": attempt,
                        "error_type": _error_type(exc),
                        "timestamp": _now(),
                        **_correlation_fields(correlation_id),
                    }
                )
        if last_error is not None:
            raise last_error
        self.memory.record(agent.agent_id, task=task, output=output)
        result = RuntimeResult(agent_id=agent.agent_id, task=task, output=output, model=route)
        self.events.publish(
            {
                "event": "agent_completed",
                "agent_id": agent.agent_id,
                "task": task,
                "attempt": attempt,
                "model": asdict(route),
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return result

    def execute_request(
        self,
        request: AgentRequest,
        *,
        credential: str,
        complexity: str = "standard",
    ) -> AgentResult:
        if request.permission != "approved":
            raise PermissionError("agent request must be approved before execution")
        runtime_result = self.execute(
            request.agent_id,
            credential=credential,
            task=request.goal,
            complexity=complexity,
            network_mode=request.network_mode,
            correlation_id=request.correlation_id,
        )
        output = runtime_result.output
        summary = getattr(output, "summary", str(output))
        confidence = float(getattr(output, "confidence", 0.0))
        evidence = tuple(getattr(output, "evidence", ()) or ())
        sources = tuple(getattr(output, "sources", ()) or evidence)
        actions = tuple(getattr(output, "actions", ()) or getattr(output, "next_actions", ()) or ())
        proposals = tuple(getattr(output, "proposals", ()) or ())
        return AgentResult(
            task_id=request.task_id,
            agent_id=request.agent_id,
            result=summary,
            confidence=confidence,
            sources=sources,
            proposals=proposals,
            actions=actions,
            reason=getattr(output, "reason", ""),
            evidence=evidence,
            correlation_id=request.correlation_id,
            status="completed",
            governance=getattr(output, "governance", None),
        )

    def monitor_agent(
        self, agent_id: str, *, check, correlation_id: str = ""
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        details = check(agent)
        record = self.scheduler.monitor(agent.agent_id, details)
        self.events.publish(
            {
                "event": "agent_monitored",
                "agent_id": agent.agent_id,
                "fields": _detail_fields(record.details),
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return record

    def update_agent(
        self, agent_id: str, *, changes: dict[str, Any], correlation_id: str = ""
    ):
        agent = self.registry.get(agent_id)
        self.scheduler._require_known(agent.agent_id)
        record = self.scheduler.update(agent.agent_id, changes)
        self.events.publish(
            {
                "event": "agent_updated",
                "agent_id": agent.agent_id,
                "fields": _detail_fields(record.details),
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return record

    def request_update(
        self,
        agent_id: str,
        *,
        credential: str,
        target_id: str,
        old: str,
        new: str,
        reason: str,
        confidence: float,
        risk: str,
        correlation_id: str = "",
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        try:
            proposal = self.approvals.request_update(
                agent,
                credential=credential,
                target_id=target_id,
                old=old,
                new=new,
                reason=reason,
                confidence=confidence,
                risk=risk,
            )
        except Exception as exc:
            self.events.publish(
                _proposal_denied_event(
                    "request_update",
                    agent_id=agent.agent_id,
                    proposal_id=None,
                    target_id=target_id,
                    reviewer=None,
                    error_type=_error_type(exc),
                    correlation_id=correlation_id,
                )
            )
            raise
        self.events.publish(
            {
                "event": "proposal_requested",
                "agent_id": agent.agent_id,
                "proposal_id": proposal.proposal_id,
                "target_id": target_id,
                "confidence": confidence,
                "risk": risk,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return proposal

    def approve_change(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reviewer_credential: str,
        correlation_id: str = "",
    ):
        try:
            proposal = self.approvals.approve_change(
                proposal_id,
                reviewer=reviewer,
                reviewer_credential=reviewer_credential,
            )
        except Exception as exc:
            self.events.publish(
                _proposal_denied_event(
                    "approve_change",
                    agent_id=None,
                    proposal_id=proposal_id,
                    target_id=None,
                    reviewer=reviewer,
                    error_type=_error_type(exc),
                    correlation_id=correlation_id,
                )
            )
            raise
        self.events.publish(
            {
                "event": "proposal_approved",
                "proposal_id": proposal.proposal_id,
                "agent_id": proposal.agent,
                "reviewer": reviewer,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return proposal

    def reject_change(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reviewer_credential: str,
        reason: str,
        correlation_id: str = "",
    ):
        try:
            proposal = self.approvals.reject_change(
                proposal_id,
                reviewer=reviewer,
                reviewer_credential=reviewer_credential,
                reason=reason,
            )
        except Exception as exc:
            self.events.publish(
                _proposal_denied_event(
                    "reject_change",
                    agent_id=None,
                    proposal_id=proposal_id,
                    target_id=None,
                    reviewer=reviewer,
                    error_type=_error_type(exc),
                    correlation_id=correlation_id,
                )
            )
            raise
        self.events.publish(
            {
                "event": "proposal_rejected",
                "proposal_id": proposal.proposal_id,
                "agent_id": proposal.agent,
                "reviewer": reviewer,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return proposal

    def expire_change(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reviewer_credential: str,
        reason: str,
        correlation_id: str = "",
    ):
        try:
            proposal = self.approvals.expire_change(
                proposal_id,
                reviewer=reviewer,
                reviewer_credential=reviewer_credential,
                reason=reason,
            )
        except Exception as exc:
            self.events.publish(
                _proposal_denied_event(
                    "expire_change",
                    agent_id=None,
                    proposal_id=proposal_id,
                    target_id=None,
                    reviewer=reviewer,
                    error_type=_error_type(exc),
                    correlation_id=correlation_id,
                )
            )
            raise
        self.events.publish(
            {
                "event": "proposal_expired",
                "proposal_id": proposal.proposal_id,
                "agent_id": proposal.agent,
                "reviewer": reviewer,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return proposal

    def request_access(
        self,
        agent_id: str,
        *,
        resource: str,
        reason: str,
        sensitivity: str,
        correlation_id: str = "",
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        try:
            self.permissions.require(agent, "request_access")
        except Exception as exc:
            self.events.publish(
                _access_request_denied_event(
                    agent.agent_id,
                    resource,
                    _error_type(exc),
                    correlation_id,
                )
            )
            raise
        request = self.access_requests.create(
            agent_id=agent.agent_id,
            resource=resource,
            reason=reason,
            sensitivity=sensitivity,
        )
        self.events.publish(
            {
                "event": "access_request_created",
                "agent_id": agent.agent_id,
                "request_id": request.request_id,
                "resource": request.resource,
                "sensitivity": request.sensitivity,
                "timestamp": request.created,
                **_correlation_fields(correlation_id),
            }
        )
        return request

    def approve_access_request(
        self,
        request_id: str,
        *,
        reviewer: str,
        reason: str,
        correlation_id: str = "",
    ):
        request = self.access_requests.approve(
            request_id,
            reviewer=reviewer,
            reason=reason,
        )
        self.events.publish(
            {
                "event": "access_request_approved",
                "agent_id": request.agent_id,
                "request_id": request.request_id,
                "reviewer": reviewer,
                "timestamp": request.review_time,
                **_correlation_fields(correlation_id),
            }
        )
        return request

    def reject_access_request(
        self,
        request_id: str,
        *,
        reviewer: str,
        reason: str,
        correlation_id: str = "",
    ):
        request = self.access_requests.reject(
            request_id,
            reviewer=reviewer,
            reason=reason,
        )
        self.events.publish(
            {
                "event": "access_request_rejected",
                "agent_id": request.agent_id,
                "request_id": request.request_id,
                "reviewer": reviewer,
                "timestamp": request.review_time,
                **_correlation_fields(correlation_id),
            }
        )
        return request

    def get_context(
        self,
        agent_id: str,
        *,
        credential: str,
        task: str,
        correlation_id: str = "",
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        return self.context.build(agent, credential=credential, task=task)

    def get_context_with_access(
        self,
        agent_id: str,
        *,
        credential: str,
        task: str,
        access_request_id: str,
        correlation_id: str = "",
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        request = self.access_requests.load(access_request_id)
        if request.agent_id != agent.agent_id:
            self.events.publish(
                _access_grant_denied_event(
                    agent.agent_id,
                    request,
                    "access_request_agent_mismatch",
                    correlation_id,
                )
            )
            raise AccessRequestDenied("access_request_agent_mismatch")
        if request.status == "used":
            self.events.publish(
                _access_grant_denied_event(
                    agent.agent_id,
                    request,
                    "access_request_already_used",
                    correlation_id,
                )
            )
            raise AccessRequestDenied("access_request_already_used")
        if request.status != "approved":
            self.events.publish(
                _access_grant_denied_event(
                    agent.agent_id,
                    request,
                    "access_request_not_approved",
                    correlation_id,
                )
            )
            raise AccessRequestDenied("access_request_not_approved")
        context = self.context.build_with_access_grant(
            agent,
            credential=credential,
            task=task,
            resource_path=request.resource,
            max_sensitivity=request.sensitivity,
        )
        used_request = self.access_requests.mark_used(request.request_id)
        self.events.publish(
            {
                "event": "access_grant_used",
                "agent_id": agent.agent_id,
                "request_id": used_request.request_id,
                "resource": used_request.resource,
                "sensitivity": used_request.sensitivity,
                "timestamp": _now(),
                **_correlation_fields(correlation_id),
            }
        )
        return context
