from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from capability_plugins.contracts import ActivationState
from capability_plugins.registry import PluginRegistry, PluginResolutionError
from runtime_core.events import EventBus

if TYPE_CHECKING:
    from orchestration.contracts import ExecutionPlan, UserIntent


@dataclass(frozen=True)
class CapabilityRequest:
    step_id: str
    capability: str
    payload: dict[str, Any]
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("step_id", "capability"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dictionary")
        if not isinstance(self.depends_on, tuple) or any(
            not isinstance(step_id, str) or not step_id.strip()
            for step_id in self.depends_on
        ):
            raise ValueError("depends_on must be a tuple of non-empty step ids")


@dataclass(frozen=True)
class PlanGap:
    step_id: str
    capability: str
    reason_code: str
    explanation: str


@dataclass(frozen=True)
class PlanningResult:
    plan: ExecutionPlan | None
    gaps: tuple[PlanGap, ...]


class CapabilityPlanner:
    """Resolve requested capability steps against ready registered providers."""

    def __init__(
        self,
        registry: PluginRegistry,
        *,
        events: EventBus | None = None,
        activate_on_demand: bool = False,
    ) -> None:
        if not isinstance(registry, PluginRegistry):
            raise TypeError("registry must be a PluginRegistry")
        if events is not None and not isinstance(events, EventBus):
            raise TypeError("events must be an EventBus or None")
        if type(activate_on_demand) is not bool:
            raise TypeError("activate_on_demand must be a bool")
        self.registry = registry
        self._events = events
        self._activate_on_demand = activate_on_demand

    def plan(
        self,
        intent: UserIntent,
        requests: Iterable[CapabilityRequest],
        *,
        assumptions: tuple[str, ...] = (),
    ) -> PlanningResult:
        request_list = tuple(requests)
        if any(not isinstance(request, CapabilityRequest) for request in request_list):
            raise TypeError("requests must contain CapabilityRequest values")

        request_by_id: dict[str, CapabilityRequest] = {}
        for request in request_list:
            if request.step_id in request_by_id:
                raise ValueError(f"duplicate step_id: {request.step_id}")
            request_by_id[request.step_id] = request

        gaps: list[PlanGap] = []
        for request in request_list:
            for dependency in request.depends_on:
                if dependency not in request_by_id:
                    gaps.append(
                        PlanGap(
                            step_id=request.step_id,
                            capability=request.capability,
                            reason_code="unknown_dependency",
                            explanation=(
                                f"Step {request.step_id!r} depends on unknown step "
                                f"{dependency!r}."
                            ),
                        )
                    )
        if gaps:
            return PlanningResult(plan=None, gaps=tuple(gaps))

        ordered_ids: list[str] = []
        completed: set[str] = set()
        remaining = set(request_by_id)
        while remaining:
            ready_ids = sorted(
                step_id
                for step_id in remaining
                if set(request_by_id[step_id].depends_on) <= completed
            )
            if not ready_ids:
                cycle_ids = sorted(remaining)
                cycle_members = _find_cycle_members(request_by_id, remaining)
                cycle_text = ", ".join(sorted(cycle_members))
                return PlanningResult(
                    plan=None,
                    gaps=tuple(
                        PlanGap(
                            step_id=step_id,
                            capability=request_by_id[step_id].capability,
                            reason_code=(
                                "dependency_cycle"
                                if step_id in cycle_members
                                else "dependency_blocked_by_cycle"
                            ),
                            explanation=(
                                f"Dependency cycle includes steps: {cycle_text}."
                                if step_id in cycle_members
                                else f"Step is blocked by dependency cycle: {cycle_text}."
                            ),
                        )
                        for step_id in cycle_ids
                    ),
                )
            for step_id in ready_ids:
                ordered_ids.append(step_id)
                completed.add(step_id)
                remaining.remove(step_id)

        resolved: dict[str, Any] = {}
        pending_activation: set[str] = set()
        for step_id in ordered_ids:
            request = request_by_id[step_id]
            try:
                resolved[step_id] = self.registry.by_capability(request.capability)
            except PluginResolutionError as exc:
                manifest = self.registry.get(exc.plugin_id)
                if (
                    self._activate_on_demand
                    and exc.status == "dormant"
                    and manifest.activation_mode == "on_demand"
                    and manifest.activation_state is ActivationState.DORMANT
                ):
                    resolved[step_id] = manifest
                    pending_activation.add(manifest.plugin_id)
                else:
                    gaps.append(
                        PlanGap(
                            step_id=step_id,
                            capability=request.capability,
                            reason_code="provider_not_ready",
                            explanation=(
                                f"Capability {request.capability!r} has no ready provider "
                                f"({exc.status})."
                            ),
                        )
                    )
            except KeyError:
                gaps.append(
                    PlanGap(
                        step_id=step_id,
                        capability=request.capability,
                        reason_code="unknown_capability",
                        explanation=(
                            f"No registered provider declares capability "
                            f"{request.capability!r}."
                        ),
                    )
                )
        if gaps:
            return PlanningResult(plan=None, gaps=tuple(gaps))

        # Contracts are delivered in parallel; defer importing them so gap and
        # graph validation remain usable while that integration is in progress.
        from orchestration.contracts import CapabilityCall, ExecutionPlan

        calls = tuple(
            CapabilityCall(
                step_id=step_id,
                plugin_id=resolved[step_id].plugin_id,
                capability=request_by_id[step_id].capability,
                payload=dict(request_by_id[step_id].payload),
                depends_on=request_by_id[step_id].depends_on,
            )
            for step_id in ordered_ids
        )
        plan = ExecutionPlan(
            flow=intent.flow,
            intent=intent,
            steps=calls,
            assumptions=tuple(assumptions),
            requires_confirmation=False,
            on_demand_plugins=tuple(sorted(pending_activation)),
        )
        if self._events is not None:
            self._events.publish(
                {
                    "event": "plan_created",
                    "flow": plan.flow.value,
                    "correlation_id": intent.correlation_id,
                    "step_count": len(plan.steps),
                }
            )
        return PlanningResult(plan=plan, gaps=())


def _find_cycle_members(
    requests: dict[str, CapabilityRequest], candidates: set[str]
) -> set[str]:
    """Return nodes in cyclic strongly connected components (Tarjan)."""
    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycle_members: set[str] = set()

    def strong_connect(step_id: str) -> None:
        nonlocal next_index
        indices[step_id] = next_index
        lowlinks[step_id] = next_index
        next_index += 1
        stack.append(step_id)
        on_stack.add(step_id)

        for dependency in sorted(requests[step_id].depends_on):
            if dependency not in candidates:
                continue
            if dependency not in indices:
                strong_connect(dependency)
                lowlinks[step_id] = min(lowlinks[step_id], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[step_id] = min(lowlinks[step_id], indices[dependency])

        if lowlinks[step_id] != indices[step_id]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == step_id:
                break
        if len(component) > 1 or step_id in requests[step_id].depends_on:
            cycle_members.update(component)

    for step_id in sorted(candidates):
        if step_id not in indices:
            strong_connect(step_id)
    return cycle_members
