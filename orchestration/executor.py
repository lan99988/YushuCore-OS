from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import re
from typing import Any

from capability_plugins.contracts import ActivationState, PluginManifest
from capability_plugins.lifecycle import PluginLifecycle
from capability_plugins.registry import PluginResolutionError
from orchestration.contracts import CapabilityCall, ExecutionPlan
from runtime_core.audit import canonical_payload_digest
from runtime_core.models import ActionAuthority, PlannedAction, PolicyDecision


@dataclass(frozen=True)
class StepExecutionResult:
    step_id: str
    status: str
    decision: PolicyDecision | None = None
    result: Any = None
    error_code: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    plan: ExecutionPlan
    status: str
    steps: tuple[StepExecutionResult, ...]
    expected_changes: tuple[str, ...] = ()


class Executor:
    """Execute an immutable plan only through policy and injected plugins."""

    def __init__(
        self,
        kernel: Any,
        plugin_executors: Mapping[str, Any],
        *,
        events: Any | None = None,
    ) -> None:
        if not isinstance(plugin_executors, Mapping):
            raise TypeError("plugin_executors must be a mapping")
        self._kernel = kernel
        self._plugin_executors = dict(plugin_executors)
        self._events = events if events is not None else getattr(kernel, "events", None)

    def execute(
        self,
        plan: ExecutionPlan,
        agent_id: str,
        dry_run: bool = True,
    ) -> ExecutionResult:
        if not isinstance(plan, ExecutionPlan):
            raise TypeError("plan must be an ExecutionPlan")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        if type(dry_run) is not bool:
            raise TypeError("dry_run must be a bool")

        ordered_steps = _topological_order(plan.steps)
        results: list[StepExecutionResult] = []
        status_by_step: dict[str, str] = {}
        expected_changes: list[str] = []
        execution_failure_seen = False
        rollback_candidates: list[tuple[Any, CapabilityCall, dict[str, Any], Any, Any]] = []
        activation_candidates = set(plan.on_demand_plugins)
        auto_activated: set[str] = set()
        completed_plugins: set[str] = set()

        for step in ordered_steps:
            manifest, manifest_error = self._resolve_manifest(
                step,
                allow_dormant=step.plugin_id in activation_candidates,
            )
            capability_effect = (
                manifest.capability_effects.get(step.capability)
                if manifest is not None
                else None
            )
            has_write_effect = (
                capability_effect in {"internal_write", "external_write"}
                if capability_effect is not None
                else bool(manifest and manifest.writes)
            )
            if manifest is not None and has_write_effect:
                expectation = f"{step.plugin_id}:{step.capability}"
                if expectation not in expected_changes:
                    expected_changes.append(expectation)

            dependency_statuses = tuple(
                status_by_step.get(dependency) for dependency in step.depends_on
            )
            dependency_success_status = "planned" if dry_run else "completed"
            if any(status != dependency_success_status for status in dependency_statuses):
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="skipped",
                    error_code="dependency_not_completed",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                continue

            if manifest_error is not None or manifest is None:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    error_code=manifest_error or "capability_unavailable",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            is_read_only = (
                capability_effect == "read_only"
                or (capability_effect is None and not manifest.writes)
            )
            if execution_failure_seen and not dry_run and is_read_only:
                # Independent read-only work may continue after a failure.
                pass
            elif (
                execution_failure_seen
                and not dry_run
                and not is_read_only
            ):
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="skipped",
                    error_code="execution_stopped_after_failure",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                continue

            action = self._planned_action(step, manifest)
            if action is None:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    error_code="invalid_payload",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            if manifest.activation_state is ActivationState.DORMANT:
                try:
                    registry = self._kernel.plugin_registry
                    PluginLifecycle(registry).transition(
                        manifest.plugin_id,
                        activation_state=ActivationState.ACTIVE,
                        actor=f"executor.{agent_id}",
                        reason="user_intent_requested_capability",
                    )
                    manifest = registry.get(manifest.plugin_id)
                    auto_activated.add(manifest.plugin_id)
                except Exception:
                    result = StepExecutionResult(
                        step_id=step.step_id,
                        status="blocked",
                        error_code="plugin_activation_failed",
                    )
                    results.append(result)
                    status_by_step[step.step_id] = result.status
                    execution_failure_seen = True
                    continue

            try:
                decision = self._kernel.authorize_action(
                    agent_id,
                    action,
                    correlation_id=plan.intent.correlation_id,
                    flow=plan.flow.value,
                )
            except Exception:
                # Do not expose exception text: it can contain caller or plugin data.
                self._publish(
                    {
                        "event": "policy_blocked",
                        "flow": plan.flow.value,
                        "correlation_id": plan.intent.correlation_id,
                        "agent_id": agent_id,
                        "plugin_id": step.plugin_id,
                        "capability": step.capability,
                        "step_id": step.step_id,
                        "reason_code": "authorization_failed",
                    }
                )
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    error_code="authorization_failed",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            if not decision.allowed or decision.approval_required:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    decision=decision,
                    error_code=decision.reason_code,
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            if dry_run:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="planned",
                    decision=decision,
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                continue

            if plan.requires_confirmation:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    decision=decision,
                    error_code="plan_confirmation_required",
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            plugin = self._plugin_executors.get(step.plugin_id)
            plugin_error = self._validate_plugin(plugin, manifest, step)
            if plugin_error is not None:
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="blocked",
                    decision=decision,
                    error_code=plugin_error,
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            context = {
                "agent_id": agent_id,
                "flow": plan.flow.value,
                "correlation_id": plan.intent.correlation_id,
                "step_id": step.step_id,
                "network_mode": getattr(self._kernel, "default_network_mode", "OFF"),
            }
            self._publish(
                {
                    "event": "plugin_started",
                    "flow": plan.flow.value,
                    "correlation_id": plan.intent.correlation_id,
                    "plugin_id": step.plugin_id,
                    "capability": step.capability,
                    "step_id": step.step_id,
                }
            )
            try:
                plugin_result = plugin.invoke(
                    step.capability,
                    _mutable_payload_copy(step.payload),
                    context,
                )
            except Exception as exc:
                error_code = _controlled_plugin_error_code(exc)
                self._publish(
                    {
                        "event": "plugin_failed",
                        "flow": plan.flow.value,
                        "correlation_id": plan.intent.correlation_id,
                        "plugin_id": step.plugin_id,
                        "capability": step.capability,
                        "step_id": step.step_id,
                        "error_type": type(exc).__name__,
                        "error_code": error_code,
                    }
                )
                result = StepExecutionResult(
                    step_id=step.step_id,
                    status="failed",
                    decision=decision,
                    error_code=error_code,
                )
                results.append(result)
                status_by_step[step.step_id] = result.status
                execution_failure_seen = True
                continue

            result = StepExecutionResult(
                step_id=step.step_id,
                status="completed",
                decision=decision,
                result=plugin_result,
            )
            results.append(result)
            status_by_step[step.step_id] = result.status
            completed_plugins.add(step.plugin_id)
            self._publish(
                {
                    "event": "plugin_completed",
                    "flow": plan.flow.value,
                    "correlation_id": plan.intent.correlation_id,
                    "plugin_id": step.plugin_id,
                    "capability": step.capability,
                    "step_id": step.step_id,
                    "status": "completed",
                }
            )
            if has_write_effect and action.reversible and callable(
                getattr(plugin, "rollback", None)
            ):
                rollback_candidates.append(
                    (
                        plugin,
                        step,
                        _mutable_payload_copy(step.payload),
                        context,
                        plugin_result,
                    )
                )

        if dry_run:
            overall_status = "dry_run"
        elif all(item.status == "completed" for item in results):
            overall_status = "completed"
        elif any(item.status == "completed" for item in results):
            overall_status = "partial"
        elif any(item.status == "failed" for item in results):
            overall_status = "failed"
        else:
            overall_status = "blocked"

        if execution_failure_seen and rollback_candidates:
            self._rollback_completed_steps(plan, rollback_candidates)
        registry = getattr(self._kernel, "plugin_registry", None)
        if registry is not None:
            lifecycle = PluginLifecycle(registry)
            for plugin_id in sorted(auto_activated - completed_plugins):
                try:
                    lifecycle.transition(
                        plugin_id,
                        activation_state=ActivationState.DORMANT,
                        actor=f"executor.{agent_id}",
                        reason="activation_rolled_back",
                    )
                except Exception:
                    self._publish(
                        {
                            "event": "plugin_activation_rollback_failed",
                            "flow": plan.flow.value,
                            "correlation_id": plan.intent.correlation_id,
                            "plugin_id": plugin_id,
                            "reason_code": "activation_rollback_failed",
                        }
                    )
        if overall_status == "partial":
            counts = {
                status: sum(item.status == status for item in results)
                for status in ("completed", "failed")
            }
            self._publish(
                {
                    "event": "partial_result",
                    "flow": plan.flow.value,
                    "correlation_id": plan.intent.correlation_id,
                    "source": "executor",
                    "status": "partial",
                    "step_count": len(results),
                    "completed_count": counts["completed"],
                    "failed_count": counts["failed"],
                    "blocked_count": sum(
                        item.status in {"blocked", "skipped"} for item in results
                    ),
                }
            )

        return ExecutionResult(
            plan=plan,
            status=overall_status,
            steps=tuple(results),
            expected_changes=tuple(expected_changes),
        )

    def _rollback_completed_steps(
        self,
        plan: ExecutionPlan,
        completed: list[tuple[Any, CapabilityCall, dict[str, Any], Any, Any]],
    ) -> None:
        self._publish(
            {
                "event": "rollback_started",
                "flow": plan.flow.value,
                "correlation_id": plan.intent.correlation_id,
                "rollback_count": len(completed),
            }
        )
        rollback_succeeded = True
        compensation_simulated = False
        for plugin, step, payload, context, result in reversed(completed):
            try:
                rollback_result = plugin.rollback(step.capability, payload, context, result)
                if rollback_result == "simulated":
                    compensation_simulated = True
            except Exception:
                rollback_succeeded = False
        self._publish(
            {
                "event": "rollback_completed",
                "flow": plan.flow.value,
                "correlation_id": plan.intent.correlation_id,
                "rollback_count": len(completed),
                "status": (
                    "failed"
                    if not rollback_succeeded
                    else "simulated"
                    if compensation_simulated
                    else "completed"
                ),
            }
        )

    def _publish(self, event: dict[str, Any]) -> None:
        if callable(getattr(self._events, "publish", None)):
            self._events.publish(event)

    def _resolve_manifest(
        self, step: CapabilityCall, *, allow_dormant: bool = False
    ) -> tuple[PluginManifest | None, str | None]:
        registry = getattr(self._kernel, "plugin_registry", None)
        if registry is None:
            return None, "plugin_registry_required"
        try:
            manifest = registry.by_capability(step.capability)
        except PluginResolutionError as exc:
            if not allow_dormant or exc.status != "dormant":
                return None, "capability_unavailable"
            try:
                manifest = registry.get(step.plugin_id)
            except KeyError:
                return None, "capability_unavailable"
            if (
                manifest.activation_mode != "on_demand"
                or manifest.activation_state is not ActivationState.DORMANT
                or step.capability not in manifest.provides
            ):
                return None, "capability_unavailable"
        except Exception:
            return None, "capability_unavailable"
        if not isinstance(manifest, PluginManifest):
            return None, "invalid_registered_manifest"
        if manifest.plugin_id != step.plugin_id:
            return None, "planned_provider_mismatch"
        return manifest, None

    @staticmethod
    def _planned_action(
        step: CapabilityCall, manifest: PluginManifest
    ) -> PlannedAction | None:
        try:
            digest = canonical_payload_digest(step.payload)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return None
        effect = manifest.capability_effects.get(step.capability)
        if effect == "read_only":
            authority = ActionAuthority.OBSERVE
            reversible = True
            external_effect = False
        elif effect in {"proposal", "internal_write"}:
            authority = ActionAuthority.AUTONOMOUS
            reversible = True
            external_effect = False
        elif effect == "external_write":
            authority = ActionAuthority.APPROVAL_REQUIRED
            reversible = False
            external_effect = True
        else:
            has_writes = bool(manifest.writes)
            authority = (
                ActionAuthority.AUTONOMOUS if has_writes else ActionAuthority.OBSERVE
            )
            reversible = not has_writes
            external_effect = has_writes
        affects_commitment = step.payload.get("affects_commitment") is True or (
            step.capability in {"calendar.create_proposal", "calendar.move_proposal"}
            and any(
                step.payload.get(marker) is True
                for marker in ("fixed_meeting", "external_commitment")
            )
        )
        return PlannedAction(
            action_id=step.step_id,
            plugin_id=step.plugin_id,
            capability=step.capability,
            authority=authority,
            reversible=reversible,
            external_effect=external_effect,
            affects_commitment=affects_commitment,
            risk=manifest.risk_level.value,
            payload_digest=digest,
            operation=step.capability,
            resource=f"plugin:{step.plugin_id}",
            required_permissions=manifest.permissions,
        )

    @staticmethod
    def _validate_plugin(
        plugin: Any,
        manifest: PluginManifest,
        step: CapabilityCall,
    ) -> str | None:
        if plugin is None:
            return "plugin_executor_missing"
        if not callable(getattr(plugin, "invoke", None)):
            return "plugin_executor_invalid"
        plugin_manifest = getattr(plugin, "manifest", None)
        if not isinstance(plugin_manifest, PluginManifest):
            return "plugin_manifest_invalid"
        declared_manifest = replace(
            plugin_manifest,
            availability=manifest.availability,
            enabled=manifest.enabled,
            activation_state=manifest.activation_state,
        )
        if declared_manifest != manifest:
            return "plugin_manifest_mismatch"
        if step.capability not in plugin_manifest.provides:
            return "plugin_capability_mismatch"
        return None


def _topological_order(steps: tuple[CapabilityCall, ...]) -> tuple[CapabilityCall, ...]:
    if any(not isinstance(step, CapabilityCall) for step in steps):
        raise TypeError("plan steps must contain only CapabilityCall values")
    step_ids = {step.step_id for step in steps}
    for step in steps:
        unknown = set(step.depends_on) - step_ids
        if unknown:
            raise ValueError("unknown dependency step_id: " + ", ".join(sorted(unknown)))

    remaining = list(steps)
    completed: set[str] = set()
    ordered: list[CapabilityCall] = []
    while remaining:
        ready = [step for step in remaining if set(step.depends_on) <= completed]
        if not ready:
            raise ValueError("execution plan dependency cycle")
        for step in ready:
            ordered.append(step)
            completed.add(step.step_id)
        ready_ids = {step.step_id for step in ready}
        remaining = [step for step in remaining if step.step_id not in ready_ids]
    return tuple(ordered)


def _mutable_payload_copy(value: Any) -> Any:
    """Thaw an immutable plan payload without sharing nested containers."""
    if isinstance(value, Mapping):
        return {key: _mutable_payload_copy(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_mutable_payload_copy(item) for item in value]
    return value


_PLUGIN_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _controlled_plugin_error_code(exc: Exception) -> str:
    value = getattr(exc, "error_code", None)
    if isinstance(value, str) and _PLUGIN_ERROR_CODE.fullmatch(value):
        return value
    return "plugin_execution_failed"
