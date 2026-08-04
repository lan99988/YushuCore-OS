from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_core.access import AccessRequestDenied, AccessRequestStore
from runtime_core.approval import ApprovalEngine
from runtime_core.config import AgentHandlerMap, load_agent_definitions
from runtime_core.context import ContextManager
from runtime_core.events import EventBus
from runtime_core.logger import RuntimeLogger
from runtime_core.memory import MemoryManager
from runtime_core.models import AgentDefinition, RuntimeContext, RuntimeResult
from runtime_core.permissions import PermissionManager
from runtime_core.policy import RuntimePolicy
from runtime_core.registry import AgentRegistry
from runtime_core.router import ModelRouter
from runtime_core.scheduler import AgentScheduler
from runtime_core.tools import ToolManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeKernel:
    def __init__(
        self,
        *,
        gateway: Any,
        state_path: str | Path,
        local_model: str,
        cloud_model: str,
        model_router: ModelRouter | None = None,
        default_network_mode: str = "OFF",
    ) -> None:
        if default_network_mode not in {"OFF", "ASSIST", "SYNC"}:
            raise ValueError("default_network_mode must be OFF, ASSIST, or SYNC")
        self.default_network_mode = default_network_mode
        self.registry = AgentRegistry()
        self.scheduler = AgentScheduler()
        self.permissions = PermissionManager()
        self.access_requests = AccessRequestStore(state_path)
        self.memory = MemoryManager(state_path)
        self.events = EventBus()
        self.logger = RuntimeLogger(state_path)
        self.events.subscribe(self.logger.write)
        self.model_router = model_router or ModelRouter(
            local_model=local_model,
            cloud_model=cloud_model,
        )
        self.context = ContextManager(gateway, self.permissions)
        self.approvals = ApprovalEngine(gateway, self.permissions)
        self.tools = ToolManager(self.permissions)

    @classmethod
    def from_policy(
        cls,
        *,
        gateway: Any,
        state_path: str | Path,
        policy: RuntimePolicy,
    ) -> "RuntimeKernel":
        return cls(
            gateway=gateway,
            state_path=state_path,
            local_model=policy.local_model,
            cloud_model=policy.cloud_model,
            model_router=policy.model_router(),
            default_network_mode=policy.network_mode,
        )

    def register_agent(self, definition: AgentDefinition) -> None:
        self.registry.register(definition)
        self.scheduler.register(definition.agent_id)

    def load_agents_from_file(self, path: str | Path, *, handlers: AgentHandlerMap) -> None:
        for definition in load_agent_definitions(path, handlers):
            self.register_agent(definition)

    def activate_agent(self, agent_id: str) -> None:
        agent = self.registry.get(agent_id)
        self.scheduler.activate(agent.agent_id)
        self.events.publish(
            {
                "event": "agent_activated",
                "agent_id": agent.agent_id,
                "timestamp": _now(),
            }
        )

    def deactivate_agent(self, agent_id: str) -> None:
        agent = self.registry.get(agent_id)
        self.scheduler.deactivate(agent.agent_id)
        self.events.publish(
            {
                "event": "agent_deactivated",
                "agent_id": agent.agent_id,
                "timestamp": _now(),
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
    ) -> RuntimeResult:
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        self.permissions.require(agent, "execute")
        knowledge_context = self.context.build(agent, credential=credential, task=task)
        selected_network_mode = network_mode or self.default_network_mode
        route = self.model_router.select(
            complexity=complexity,
            network_mode=selected_network_mode,
        )
        self.events.publish(
            {
                "event": "agent_started",
                "agent_id": agent.agent_id,
                "task": task,
                "timestamp": _now(),
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
        )
        try:
            output = agent.handler(runtime_context)
        except Exception as exc:
            self.events.publish(
                {
                    "event": "agent_failed",
                    "agent_id": agent.agent_id,
                    "task": task,
                    "error": str(exc),
                    "timestamp": _now(),
                }
            )
            raise
        self.memory.record(agent.agent_id, task=task, output=output)
        result = RuntimeResult(agent_id=agent.agent_id, task=task, output=output, model=route)
        self.events.publish(
            {
                "event": "agent_completed",
                "agent_id": agent.agent_id,
                "task": task,
                "model": asdict(route),
                "timestamp": _now(),
            }
        )
        return result

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
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        return self.approvals.request_update(
            agent,
            credential=credential,
            target_id=target_id,
            old=old,
            new=new,
            reason=reason,
            confidence=confidence,
            risk=risk,
        )

    def approve_change(self, proposal_id: str, *, reviewer: str, reviewer_credential: str):
        return self.approvals.approve_change(
            proposal_id,
            reviewer=reviewer,
            reviewer_credential=reviewer_credential,
        )

    def request_access(
        self,
        agent_id: str,
        *,
        resource: str,
        reason: str,
        sensitivity: str,
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        self.permissions.require(agent, "request_access")
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
            }
        )
        return request

    def approve_access_request(self, request_id: str, *, reviewer: str, reason: str):
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
            }
        )
        return request

    def reject_access_request(self, request_id: str, *, reviewer: str, reason: str):
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
            }
        )
        return request

    def get_context(self, agent_id: str, *, credential: str, task: str):
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
    ):
        agent = self.registry.get(agent_id)
        self.scheduler.require_active(agent.agent_id)
        request = self.access_requests.load(access_request_id)
        if request.agent_id != agent.agent_id:
            raise AccessRequestDenied("access_request_agent_mismatch")
        if request.status != "approved":
            raise AccessRequestDenied("access_request_not_approved")
        context = self.context.build_with_access_grant(
            agent,
            credential=credential,
            task=task,
            resource_path=request.resource,
            max_sensitivity=request.sensitivity,
        )
        self.events.publish(
            {
                "event": "access_grant_used",
                "agent_id": agent.agent_id,
                "request_id": request.request_id,
                "resource": request.resource,
                "sensitivity": request.sensitivity,
                "timestamp": _now(),
            }
        )
        return context
