from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any

from orchestration import CapabilityRequest, FlowName, UserIntent

from experience_layer.contracts import (
    ExperienceItem,
    ExperienceRequest,
    ExperienceResponse,
    thaw_snapshot,
)


class PlanFlow:
    """Turn a user goal into a reviewable project, task, and calendar plan."""

    def __init__(self, planner: Any, executor: Any, *, agent_id: str) -> None:
        if not callable(getattr(planner, "plan", None)):
            raise TypeError("planner must provide plan")
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must provide execute")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        self._planner = planner
        self._executor = executor
        self._agent_id = agent_id

    def run(
        self, request: ExperienceRequest, intent: UserIntent
    ) -> ExperienceResponse:
        if not isinstance(request, ExperienceRequest):
            raise TypeError("request must be an ExperienceRequest")
        if not isinstance(intent, UserIntent) or intent.flow is not FlowName.PLAN:
            raise ValueError("plan flow requires a Plan intent")

        context = request.context
        goal = _goal_snapshot(context.get("goal"), request.text)
        current_state = _mapping_snapshot(context.get("current_state"))
        gaps = _gap_snapshots(context.get("gaps", context.get("gap")))
        review_input, review_error = _review_context(context)

        understood = [
            ExperienceItem(
                item_id=goal["goal_id"],
                title=f"目标：{goal['title']}",
                reason_code="goal_defined",
                after=goal,
            )
        ]
        uncertainties: list[ExperienceItem] = []
        if current_state is None:
            uncertainties.append(
                ExperienceItem(
                    item_id="plan-current-state-missing",
                    title="当前状态信息尚不完整，需要补充后才能估算差距。",
                    reason_code="current_state_missing",
                )
            )
        else:
            understood.append(
                ExperienceItem(
                    item_id="plan-current-state",
                    title="已纳入当前状态信息。",
                    reason_code="current_state_recorded",
                    after=current_state,
                )
            )

        suggestions: list[ExperienceItem] = []
        if not gaps:
            uncertainties.append(
                ExperienceItem(
                    item_id="plan-gap-missing",
                    title="目标与当前状态之间的具体差距仍需确认。",
                    reason_code="gap_data_missing",
                )
            )
        else:
            for index, gap in enumerate(gaps, start=1):
                gap_id = _safe_id(
                    gap.get("gap_id") or gap.get("id"), f"gap-{index}"
                )
                gap_title = _text(gap.get("title") or gap.get("description"))
                if not gap_title:
                    gap_title = "待澄清的目标差距"
                before = _optional_snapshot(gap.get("current"))
                after = _optional_snapshot(gap.get("desired"))
                suggestions.append(
                    ExperienceItem(
                        item_id=gap_id,
                        title=f"目标差距：{gap_title}",
                        reason_code="goal_gap_identified",
                        before=before,
                        after=after,
                    )
                )

        if review_input is not None:
            understood.append(
                ExperienceItem(
                    item_id="plan-next-cycle-context",
                    title="已纳入上一周期复盘提出的下一周期焦点。",
                    reason_code="next_cycle_context",
                    after=review_input,
                )
            )

        if review_error is not None:
            uncertainties.append(
                ExperienceItem(
                    item_id="plan-next-cycle-invalid",
                    title="上一周期复盘的下一周期输入缺少有效焦点或周期。",
                    reason_code="next_cycle_context_invalid",
                )
            )
        project_plan = _mapping_snapshot(context.get("project_plan"))
        if current_state is None or not gaps or review_error is not None or project_plan is None:
            if project_plan is None and current_state is not None and gaps:
                uncertainties.append(
                    ExperienceItem(
                        item_id="plan-structure-missing",
                        title="尚无经过确认的项目、里程碑和任务分解，暂不生成提案。",
                        reason_code="structured_project_plan_missing",
                    )
                )
            uncertainties.append(
                ExperienceItem(
                    item_id="plan-project-unavailable",
                    title="补齐规划上下文后，才能形成项目计划。",
                    reason_code="project_plan_unavailable",
                )
            )
            return _response(
                status="needs_clarification",
                understood=understood,
                suggestions=suggestions,
                uncertainties=uncertainties,
            )

        project = _mapping_snapshot(project_plan.get("project"))
        if project is None:
            uncertainties.append(
                ExperienceItem(
                    item_id="plan-project-object-missing",
                    title="结构化方案中缺少独立的项目对象，无法安全生成后续安排。",
                    reason_code="project_object_missing",
                )
            )
            return _response(
                status="partial",
                understood=understood,
                suggestions=suggestions,
                uncertainties=uncertainties,
            )

        project_id = _safe_id(
            project.get("project_id") or project.get("id"), "project-plan"
        )
        project_title = _text(
            project.get("title") or project.get("name") or project.get("project_name")
        ) or "目标实施项目"
        project_snapshot = dict(project)
        project_snapshot.update({"project_id": project_id, "title": project_title})
        if review_input is not None:
            project_snapshot["next_cycle_context"] = review_input
        suggestions.append(
            ExperienceItem(
                item_id=project_id,
                title=f"项目建议：{project_title}",
                reason_code="project_proposed",
                after=project_snapshot,
            )
        )
        project_item = suggestions[-1]

        milestones = _mapping_sequence(project_plan.get("milestones"))
        milestone_steps: dict[str, str] = {}
        milestone_requests: list[tuple[CapabilityRequest, tuple[str, Any]]] = []
        for index, milestone in enumerate(milestones, start=1):
            milestone_id = _safe_id(
                milestone.get("milestone_id") or milestone.get("id"),
                f"milestone-{index}",
            )
            milestone_title = _text(
                milestone.get("title") or milestone.get("name")
            ) or f"阶段 {index}"
            milestone_snapshot = dict(milestone)
            milestone_snapshot.update(
                {
                    "milestone_id": milestone_id,
                    "title": milestone_title,
                    "project_id": project_id,
                }
            )
            suggestions.append(
                ExperienceItem(
                    item_id=milestone_id,
                    title=f"里程碑建议：{milestone_title}",
                    reason_code="milestone_proposed",
                    after=milestone_snapshot,
                )
            )
            step_id = f"milestone-proposal-{milestone_id}"
            milestone_steps[milestone_id] = step_id
            milestone_payload: dict[str, Any] = {"title": milestone_title}
            for field_name in ("description", "due_at"):
                value = milestone.get(field_name)
                if isinstance(value, str) and value.strip():
                    milestone_payload[field_name] = value.strip()
            milestone_requests.append(
                (
                    CapabilityRequest(
                        step_id,
                        "project.milestone_proposal",
                        {
                            "project_proposal_id": project_id,
                            "milestone": milestone_payload,
                        },
                        depends_on=("plan-project-proposal",),
                    ),
                    ("milestone", suggestions[-1]),
                )
            )

        tasks = _mapping_sequence(project_plan.get("tasks"))
        calendar_proposals = _mapping_sequence(
            project_plan.get("calendar_proposals")
        )
        confirmations: list[ExperienceItem] = []
        task_items: list[tuple[dict[str, Any], ExperienceItem]] = []
        for index, task in enumerate(tasks, start=1):
            normalized, item = _task_item(task, index, project_id)
            if item is None:
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"plan-task-invalid-{index}",
                        title="计划中有一项任务缺少有效标题，未生成提案。",
                        reason_code="invalid_task_proposal",
                    )
                )
                continue
            task_items.append((normalized, item))
            if _is_commitment(normalized):
                confirmations.append(
                    ExperienceItem(
                        item_id=item.item_id,
                        title=f"请确认承诺任务：{normalized['title']}。",
                        reason_code="external_commitment_requires_confirmation",
                        after=normalized,
                        requires_confirmation=True,
                    )
                )
            else:
                # This is a normalized, local proposal. Today can consume it
                # without depending on a plugin-specific result shape.
                suggestions.append(item)

        project_request = CapabilityRequest(
            "plan-project-proposal",
            "project.create_proposal",
            {
                "goal": goal["title"],
                "task_status": _project_task_status(tasks),
                "progress": _project_progress(project_plan),
            },
            depends_on=("plan-goal-parse",),
        )
        goal_request = CapabilityRequest(
            "plan-goal-parse",
            "goal.parse",
            {"goal": {"title": goal["title"]}},
        )
        task_and_calendar_requests = _proposal_requests(
            task_items,
            calendar_proposals,
            project_id,
            milestone_steps=milestone_steps,
            task_steps={item.item_id: f"task-proposal-{item.item_id}" for _, item in task_items},
        )
        proposal_requests = (
            (goal_request, ("goal", understood[0])),
            (project_request, ("project", project_item)),
            *milestone_requests,
            *task_and_calendar_requests,
        )
        for index, proposal in enumerate(calendar_proposals, start=1):
            proposal_id = _safe_id(
                proposal.get("proposal_id") or proposal.get("event_id") or proposal.get("id"),
                f"calendar-{index}",
            )
            normalized_proposal = dict(proposal)
            normalized_proposal["proposal_id"] = proposal_id
            if not any(
                request_item.step_id == f"calendar-proposal-{proposal_id}"
                for request_item, _ in task_and_calendar_requests
            ):
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"uncertainty-{proposal_id}",
                        title="日历提案缺少完整时间或标题，需补充后才能生成安排。",
                        reason_code="calendar_proposal_details_missing",
                    )
                )
            confirmations.append(_calendar_confirmation(normalized_proposal, project_id))

        assumptions = [
            "目标、项目、里程碑和任务分别建模，不将目标直接转换为待办。",
            "项目结构来自显式的受控方案输入；适配器仅生成审核提案，不写入外部系统。",
            "任务、里程碑和日历请求按依赖关系排序；日历安排及外部承诺必须由用户确认。",
        ]
        if review_input is not None:
            assumptions.extend(
                (
                    f"下一周期焦点：{review_input['focus']}",
                    f"下一周期范围：{review_input['period']}",
                )
            )
        try:
            planning_requests = tuple(item[0] for item in proposal_requests)
            planning = self._planner.plan(
                intent, planning_requests, assumptions=tuple(assumptions)
            )
        except Exception:
            return _planning_failure(understood, suggestions, uncertainties)

        if planning.plan is None or planning.gaps:
            uncertainties.extend(_planning_uncertainties(planning.gaps))
            return _response(
                status="blocked",
                understood=understood,
                suggestions=suggestions,
                confirmations=confirmations,
                uncertainties=uncertainties,
                diagnostics=_gap_diagnostics(planning.gaps),
            )

        try:
            execution = self._executor.execute(
                planning.plan,
                agent_id=self._agent_id,
                dry_run=request.dry_run,
            )
        except Exception:
            return _planning_failure(understood, suggestions, uncertainties)

        results_by_step = {
            getattr(step, "step_id", None): step
            for step in getattr(execution, "steps", ())
        }
        for capability_request, (kind, source) in proposal_requests:
            step = results_by_step.get(capability_request.step_id)
            status = _status(step)
            if status in {"completed", "planned"}:
                continue
            if _requires_confirmation(step):
                if kind == "task" and source is not None:
                    task_item = source
                    suggestions[:] = [
                        item for item in suggestions if item.item_id != task_item.item_id
                    ]
                    if not any(item.item_id == task_item.item_id for item in confirmations):
                        confirmations.append(
                            ExperienceItem(
                                item_id=task_item.item_id,
                                title=f"请确认任务提案：{task_item.after['title']}。",
                                reason_code="task_proposal_requires_confirmation",
                                after=task_item.after,
                                requires_confirmation=True,
                            )
                        )
                elif kind == "project":
                    confirmations.append(
                        ExperienceItem(
                            item_id=project_id,
                            title=f"请确认项目建议：{project_title}。",
                            reason_code="project_proposal_requires_confirmation",
                            after=project_snapshot,
                            requires_confirmation=True,
                        )
                    )
                elif kind == "milestone" and source is not None:
                    confirmations.append(
                        ExperienceItem(
                            item_id=source.item_id,
                            title=f"请确认里程碑建议：{source.after['title']}。",
                            reason_code="milestone_proposal_requires_confirmation",
                            after=source.after,
                            requires_confirmation=True,
                        )
                    )
                continue
            uncertainties.append(
                ExperienceItem(
                    item_id=f"uncertainty-{_safe_id(capability_request.step_id, 'plan-step')}",
                    title="一项计划提案暂不可用；现有外部安排不会被修改。",
                    reason_code=_step_reason(step, "proposal_execution_unavailable"),
                )
            )

        status = "partial" if uncertainties or confirmations else "completed"
        diagnostics = [
            {"step_id": capability_request.step_id, "capability": capability_request.capability}
            for capability_request, _ in proposal_requests
        ]
        return _response(
            status=status,
            understood=understood,
            suggestions=suggestions,
            confirmations=confirmations,
            uncertainties=uncertainties,
            diagnostics=diagnostics,
        )


def _response(
    *,
    status: str,
    understood: Sequence[ExperienceItem],
    suggestions: Sequence[ExperienceItem],
    confirmations: Sequence[ExperienceItem] = (),
    uncertainties: Sequence[ExperienceItem] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
) -> ExperienceResponse:
    return ExperienceResponse(
        flow=FlowName.PLAN,
        status=status,
        understood=tuple(understood),
        suggestions=tuple(suggestions),
        confirmations=tuple(confirmations),
        uncertainties=tuple(uncertainties),
        diagnostics=tuple(diagnostics),
    )


def _planning_failure(
    understood: Sequence[ExperienceItem],
    suggestions: Sequence[ExperienceItem],
    uncertainties: Sequence[ExperienceItem],
) -> ExperienceResponse:
    return _response(
        status="blocked",
        understood=understood,
        suggestions=suggestions,
        uncertainties=(
            *uncertainties,
            ExperienceItem(
                item_id="plan-flow-unavailable",
                title="暂时无法生成计划，请稍后重试。",
                reason_code="planning_failed",
            ),
        ),
    )


def _goal_snapshot(value: Any, fallback_text: str) -> dict[str, Any]:
    source = _mapping_snapshot(value) or {}
    title = _text(source.get("title") or source.get("name")) or fallback_text.strip()
    goal_id = _safe_id(source.get("goal_id") or source.get("id"), "goal-main")
    result: dict[str, Any] = {"goal_id": goal_id, "title": title}
    for key in ("description", "success_criteria", "target_date"):
        if key in source:
            result[key] = source[key]
    return result


def _mapping_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        result = thaw_snapshot(value)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _optional_snapshot(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return _mapping_snapshot(value)
    if value is None:
        return None
    return {"value": thaw_snapshot(value)}


def _gap_snapshots(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = value
    elif isinstance(value, str) and value.strip():
        values = ({"title": value.strip()},)
    else:
        return []
    return [snapshot for item in values if (snapshot := _mapping_snapshot(item)) is not None]


def _mapping_sequence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [snapshot for item in value if (snapshot := _mapping_snapshot(item)) is not None]


def _task_item(
    task: Mapping[str, Any], index: int, project_id: str
) -> tuple[dict[str, Any], ExperienceItem | None]:
    title = _text(task.get("title") or task.get("name"))
    if not title:
        return {}, None
    task_id = _safe_id(
        task.get("task_guid") or task.get("item_id") or task.get("task_id") or task.get("id"),
        f"task-{index}",
    )
    normalized = {
        "task_guid": task_id,
        "item_id": task_id,
        "title": title,
        "project_id": _safe_id(task.get("project_id"), project_id),
        "milestone_id": _safe_id(task.get("milestone_id"), "milestone-unassigned"),
        "item_type": "task",
        "movable": task.get("movable") is True,
        "external_commitment": _is_commitment(task),
        "affects_commitment": _is_commitment(task),
        "forced_deadline": task.get("forced_deadline") is True,
    }
    due = task.get("deadline") or task.get("due_at")
    if isinstance(due, str) and due.strip():
        normalized["deadline"] = due
        normalized["due_at"] = due
    for key in (
        "start",
        "end",
        "start_at",
        "end_at",
        "suggested_start",
        "work_mode",
        "downgrade_allowed",
        "energy",
        "energy_requirement",
        "priority",
        "est_time",
        "estimated_minutes",
    ):
        if key in task:
            normalized[key] = thaw_snapshot(task[key])
    if "est_time" not in normalized and type(normalized.get("estimated_minutes")) is int:
        normalized["est_time"] = normalized["estimated_minutes"]
    return normalized, ExperienceItem(
        item_id=task_id,
        title=f"任务建议：{title}",
        reason_code="task_proposed",
        after=normalized,
    )


def _proposal_requests(
    task_items: Sequence[tuple[dict[str, Any], ExperienceItem]],
    calendar_proposals: Sequence[Mapping[str, Any]],
    project_id: str,
    *,
    milestone_steps: Mapping[str, str],
    task_steps: Mapping[str, str],
) -> list[tuple[CapabilityRequest, tuple[str, Any]]]:
    result: list[tuple[CapabilityRequest, tuple[str, Any]]] = []
    for task, item in task_items:
        payload: dict[str, Any] = {
            "title": task["title"],
            "evidence": [
                f"project:{project_id}",
                f"task:{item.item_id}",
            ],
            "project_id": task.get("project_id") or project_id,
            "due_at": task.get("due_at", task.get("deadline", "")),
        }
        if task.get("affects_commitment") is True:
            payload["affects_commitment"] = True
            payload["external_commitment"] = True
        step_id = f"task-proposal-{item.item_id}"
        dependency = milestone_steps.get(
            task.get("milestone_id"), "plan-project-proposal"
        )
        result.append(
            (
                CapabilityRequest(
                    step_id,
                    "task.create_proposal",
                    payload,
                    depends_on=(dependency,),
                ),
                ("task", item),
            )
        )
    for index, proposal in enumerate(calendar_proposals, start=1):
        proposal_id = _safe_id(
            proposal.get("proposal_id") or proposal.get("event_id") or proposal.get("id"),
            f"calendar-{index}",
        )
        summary = _text(proposal.get("summary") or proposal.get("title"))
        start = _text(proposal.get("start_iso") or proposal.get("start"))
        end = _text(proposal.get("end_iso") or proposal.get("end"))
        if not summary or not start or not end:
            continue
        payload = {
            "summary": summary,
            "start_iso": start,
            "end_iso": end,
        }
        for marker in ("fixed_meeting", "external_commitment", "affects_commitment"):
            if type(proposal.get(marker)) is bool:
                payload[marker] = proposal[marker]
        if _is_commitment(proposal):
            payload["affects_commitment"] = True
            payload["external_commitment"] = True
        step_id = f"calendar-proposal-{proposal_id}"
        task_id = _safe_id(
            proposal.get("task_id")
            or proposal.get("task_guid")
            or proposal.get("item_id"),
            "",
        )
        milestone_id = _safe_id(proposal.get("milestone_id"), "")
        dependency = task_steps.get(
            task_id,
            milestone_steps.get(milestone_id, "plan-project-proposal"),
        )
        result.append(
            (
                CapabilityRequest(
                    step_id,
                    "calendar.create_proposal",
                    payload,
                    depends_on=(dependency,),
                ),
                ("calendar", dict(proposal, proposal_id=proposal_id, summary=summary, start_iso=start, end_iso=end)),
            )
        )
    return result


def _calendar_confirmation(
    proposal: Mapping[str, Any], project_id: str
) -> ExperienceItem:
    proposal_id = _safe_id(proposal.get("proposal_id"), "calendar-proposal")
    after = {
        "proposal_id": proposal_id,
        "summary": proposal.get("summary") or proposal.get("title") or "待确认的日历安排",
        "project_id": project_id,
        "requires_time_selection": not bool(
            _text(proposal.get("start_iso")) and _text(proposal.get("end_iso"))
        ),
    }
    start = proposal.get("start_iso") or proposal.get("start")
    end = proposal.get("end_iso") or proposal.get("end")
    if isinstance(start, str) and start.strip():
        after["start_iso"] = start
    if isinstance(end, str) and end.strip():
        after["end_iso"] = end
    return ExperienceItem(
        item_id=proposal_id,
        title=f"请确认日历安排：{after['summary']}。",
        reason_code="calendar_proposal_confirmation",
        after=after,
        requires_confirmation=True,
    )


def _status(step: Any) -> str:
    status = getattr(step, "status", "missing")
    return status if isinstance(status, str) else "invalid"


def _step_reason(step: Any, fallback: str) -> str:
    decision = getattr(step, "decision", None)
    value = getattr(decision, "reason_code", None) or getattr(step, "error_code", None)
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", value) else fallback


def _planning_uncertainties(gaps: Sequence[Any]) -> tuple[ExperienceItem, ...]:
    result = []
    for index, gap in enumerate(gaps, start=1):
        reason = getattr(gap, "reason_code", None)
        result.append(
            ExperienceItem(
                item_id=f"plan-gap-{index}",
                title="所需规划能力暂不可用，当前数据未写入外部系统。",
                reason_code=(
                    reason
                    if isinstance(reason, str)
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason)
                    else "planning_provider_unavailable"
                ),
            )
        )
    return tuple(result)


def _gap_diagnostics(gaps: Sequence[Any]) -> tuple[dict[str, Any], ...]:
    result = []
    for gap in gaps:
        reason = getattr(gap, "reason_code", None)
        result.append(
            {
                "step_id": getattr(gap, "step_id", "unknown"),
                "capability": getattr(gap, "capability", "unknown"),
                "reason_code": (
                    reason
                    if isinstance(reason, str)
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason)
                    else "planning_provider_unavailable"
                ),
            }
        )
    return tuple(result)


def _is_commitment(item: Mapping[str, Any]) -> bool:
    return any(
        item.get(marker) is True
        for marker in ("external_commitment", "affects_commitment")
    )


def _requires_confirmation(step: Any) -> bool:
    decision = getattr(step, "decision", None)
    return getattr(decision, "approval_required", False) is True


def _review_context(context: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if "review_input" not in context:
        return None, None
    value = _mapping_snapshot(context.get("review_input"))
    if value is None:
        return None, "invalid"
    if isinstance(value.get("after"), Mapping):
        value = _mapping_snapshot(value["after"])
    if value is None:
        return None, "invalid"
    focus = _text(value.get("focus"))
    period = _text(value.get("period"))
    if not focus or not period:
        return None, "invalid"
    result = {"focus": focus, "period": period}
    reason = _text(value.get("reason"))
    if reason:
        result["reason"] = reason
    return result, None


def _project_task_status(tasks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for task in tasks:
        title = _text(task.get("title") or task.get("name"))
        status = _text(task.get("status")) or "pending"
        if title:
            result[title] = status
    return result


def _project_progress(project_plan: Mapping[str, Any]) -> float:
    value = project_plan.get("progress", 0.0)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        return 0.0
    return float(value)


def _project_reference(project: Mapping[str, Any], project_id: str) -> str:
    for key in ("project_ref", "project_name", "name"):
        value = _text(project.get(key))
        if value:
            return value
    return project_id


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_id(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        normalized = re.sub(r"[^a-z0-9_.:-]+", "-", value.casefold()).strip("-.:_")
        if normalized:
            if not "a" <= normalized[0] <= "z":
                normalized = f"id-{normalized}"
            return normalized[:128]
    return fallback
