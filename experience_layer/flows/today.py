from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
import re
from typing import Any

from orchestration import CapabilityRequest, FlowName, UserIntent
from personal_intelligence.models import PersonalRuleStatus, PersonalRuleTarget

from experience_layer.contracts import (
    ExperienceItem,
    ExperienceRequest,
    ExperienceResponse,
    thaw_snapshot,
)


_READS = (
    ("today-calendar", "calendar.list_events"),
    ("today-tasks", "task.list"),
    ("today-energy", "body.current_energy"),
)
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class TodayFlow:
    """Build a local Today view from governed, read-only capability results."""

    def __init__(
        self, planner: Any, executor: Any, *, agent_id: str, rule_provider: Any = None
    ) -> None:
        if not callable(getattr(planner, "plan", None)):
            raise TypeError("planner must provide plan")
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must provide execute")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        self._planner = planner
        self._executor = executor
        self._agent_id = agent_id
        self._rule_provider = rule_provider

    def run(
        self, request: ExperienceRequest, intent: UserIntent
    ) -> ExperienceResponse:
        if not isinstance(request, ExperienceRequest):
            raise TypeError("request must be an ExperienceRequest")
        if not isinstance(intent, UserIntent) or intent.flow is not FlowName.TODAY:
            raise ValueError("today flow requires a Today intent")

        target_date = _target_date(request.context)
        requests = _read_requests(request.context, target_date)
        planning = self._planner.plan(
            intent,
            requests,
            assumptions=(
                "只读取日历、任务和身体能量；不写回任何来源。",
                "固定日历和外部承诺作为硬约束，草案调整不代表外部变更。",
            ),
        )
        if planning.plan is None or planning.gaps:
            gaps = tuple(planning.gaps)
            uncertainties = tuple(
                ExperienceItem(
                    item_id=f"today-plan-gap-{index}",
                    title="今日视图所需的数据暂不可用。",
                    reason_code=_safe_reason(gap.reason_code),
                )
                for index, gap in enumerate(gaps, start=1)
            )
            if not uncertainties:
                uncertainties = (
                    ExperienceItem(
                        item_id="today-plan-unavailable",
                        title="暂时无法生成今日视图，请稍后重试。",
                        reason_code="planning_unavailable",
                    ),
                )
            return ExperienceResponse(
                flow=FlowName.TODAY,
                status="blocked",
                uncertainties=uncertainties,
                diagnostics=tuple(
                    {
                        "step_id": gap.step_id,
                        "capability": gap.capability,
                        "reason_code": gap.reason_code,
                    }
                    for gap in gaps
                ),
            )

        execution = self._executor.execute(
            planning.plan,
            agent_id=self._agent_id,
            dry_run=request.dry_run,
        )
        results_by_step = {step.step_id: step for step in execution.steps}
        sources: dict[str, Any] = {}
        diagnostics: list[dict[str, Any]] = []
        uncertainties: list[ExperienceItem] = []
        for step_id, capability in _READS:
            step = results_by_step.get(step_id)
            if step is None:
                reason = "step_result_missing"
                sources[step_id] = None
            elif step.status != "completed":
                reason = _safe_reason(step.error_code or step.status)
                sources[step_id] = None
            else:
                reason = None
                sources[step_id] = step.result
            diagnostics.append(
                {
                    "step_id": step_id,
                    "capability": capability,
                    "status": "unavailable" if reason else "completed",
                    "reason_code": reason or "source_read",
                }
            )
            if reason is not None:
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"today-source-{step_id}",
                        title=_source_unavailable_title(step_id),
                        reason_code=reason,
                    )
                )

        events, calendar_error = _calendar_events(sources["today-calendar"])
        tasks, task_error = _tasks(sources["today-tasks"])
        energy, energy_error = _energy(sources["today-energy"])
        for source_id, reason in (
            ("today-calendar", calendar_error),
            ("today-tasks", task_error),
            ("today-energy", energy_error),
        ):
            if reason is None or sources[source_id] is None:
                continue
            uncertainties.append(
                ExperienceItem(
                    item_id=f"today-invalid-{source_id}",
                    title=_source_unavailable_title(source_id),
                    reason_code=reason,
                )
            )
            for entry in diagnostics:
                if entry["step_id"] == source_id:
                    entry["status"] = "invalid"
                    entry["reason_code"] = reason

        valid_sources = sum(
            value is not None
            for value, error in (
                (events, calendar_error),
                (tasks, task_error),
                (energy, energy_error),
            )
            if error is None
        )
        hard_constraints: list[ExperienceItem] = []
        suggestions: list[ExperienceItem] = []
        adjustments: list[ExperienceItem] = []
        confirmations: list[ExperienceItem] = []
        low_energy = energy is not None and _is_low_energy(energy)

        if events is not None:
            calendar_constraints, calendar_suggestions = _calendar_items(events)
            hard_constraints.extend(calendar_constraints)
            suggestions.extend(calendar_suggestions)
        if tasks is not None:
            (
                task_items,
                task_suggestions,
                task_adjustments,
                task_confirmations,
            ) = _task_items(
                tasks,
                target_date,
                low_energy=low_energy,
                events=events or [],
            )
            hard_constraints.extend(task_items)
            suggestions.extend(task_suggestions)
            adjustments.extend(task_adjustments)
            confirmations.extend(task_confirmations)
        if low_energy:
            suggestions.append(
                ExperienceItem(
                    item_id="today-low-energy",
                    title="身体能量偏低，建议优先安排轻量工作并留出恢复时间。",
                    reason_code="low_energy",
                )
            )
        if tasks is not None and low_energy:
            confirmations.extend(_energy_deadline_confirmations(tasks, target_date))

        if valid_sources == 0:
            status = "blocked"
        elif uncertainties:
            status = "partial"
        elif execution.status == "partial":
            status = "partial"
        elif execution.status in {"failed", "blocked"}:
            status = "partial"
        else:
            status = "completed"

        if (
            self._rule_provider is not None
            and valid_sources > 0
            and not hard_constraints
            and not confirmations
            and not adjustments
        ):
            suggestions.extend(
                _personal_rule_suggestions(
                    self._rule_provider,
                    request.context,
                    target=PersonalRuleTarget.TODAY,
                )
            )

        return ExperienceResponse(
            flow=FlowName.TODAY,
            status=status,
            hard_constraints=tuple(hard_constraints),
            suggestions=tuple(suggestions),
            automatic_adjustments=tuple(adjustments),
            confirmations=tuple(confirmations),
            uncertainties=tuple(uncertainties),
            diagnostics=tuple(diagnostics),
        )


def _personal_rule_suggestions(
    provider: Any,
    _context: Mapping[str, Any],
    *,
    target: PersonalRuleTarget,
) -> list[ExperienceItem]:
    # A caller cannot broaden the rule scope through request context.
    scope = ("planning",)
    try:
        rules = provider.active_rules(scope=scope, target=target)
    except (OSError, ValueError, KeyError):
        return []
    suggestions = []
    for rule in rules:
        if (
            rule.status is not PersonalRuleStatus.ACTIVE
            or rule.target is not target
            or not set(rule.scope).issubset(scope)
            or not rule.supporting_evidence
        ):
            continue
        suggestions.append(
            ExperienceItem(
                item_id=f"today-rule-{rule.rule_id}",
                title=f"个人规则建议：{rule.suggested_action}（依据：{rule.hypothesis}）",
                reason_code="personal_rule_guidance",
                rule_id=rule.rule_id,
                evidence_refs=tuple(rule.supporting_evidence),
                confidence=rule.confidence,
            )
        )
    return suggestions


def _target_date(context: Mapping[str, Any]) -> str | None:
    value = context.get("target_date")
    if value is None:
        return date.today().isoformat()
    if not isinstance(value, str):
        raise ValueError("target_date must be an ISO date string")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("target_date must be an ISO date string") from exc
    return value


def _read_requests(
    context: Mapping[str, Any], target_date: str | None
) -> tuple[CapabilityRequest, ...]:
    day_filter = {"target_date": target_date} if target_date else {}
    energy_payload: dict[str, Any] = {}
    body_snapshot = context.get("body_snapshot")
    if body_snapshot is not None:
        energy_payload["snapshot"] = thaw_snapshot(body_snapshot)
    return (
        CapabilityRequest(
            "today-calendar",
            "calendar.list_events",
            {"target_date": target_date} if target_date else {},
        ),
        CapabilityRequest(
            "today-tasks", "task.list", {"filters": day_filter}
        ),
        CapabilityRequest("today-energy", "body.current_energy", energy_payload),
    )


def _calendar_events(value: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, Mapping) or not isinstance(value.get("events"), list):
        return None, "invalid_calendar_data"
    events = value["events"]
    if any(not isinstance(item, Mapping) for item in events):
        return None, "invalid_calendar_data"
    return [dict(item) for item in events], None


def _tasks(value: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, Mapping):
        value = value.get("tasks")
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        return None, "invalid_task_data"
    tasks = [dict(item) for item in value]
    if any(not _item_title(item) for item in tasks):
        return None, "invalid_task_data"
    return tasks, None


def _energy(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, Mapping):
        return None, "invalid_energy_data"
    projection = value.get("today_energy_context", value)
    if not isinstance(projection, Mapping):
        return None, "invalid_energy_data"
    score = projection.get("body_battery_score")
    if score is not None and (type(score) not in {int, float} or not 0 <= score <= 100):
        return None, "invalid_energy_data"
    sleep_hours = projection.get("sleep_hours")
    if sleep_hours is not None and (
        type(sleep_hours) not in {int, float} or not 0 <= sleep_hours <= 24
    ):
        return None, "invalid_energy_data"
    return dict(projection), None


def _calendar_items(
    events: list[dict[str, Any]],
) -> tuple[list[ExperienceItem], list[ExperienceItem]]:
    constraints: list[ExperienceItem] = []
    suggestions: list[ExperienceItem] = []
    for index, event in enumerate(events, start=1):
        title = _item_title(event) or "日历安排"
        external = any(
            event.get(marker) is True
            for marker in ("external_commitment", "affects_commitment")
        )
        explicitly_fixed = event.get("fixed_meeting") is True
        fixed = explicitly_fixed or event.get("movable") is not True
        item_id = _safe_item_id(
            event.get("event_id") or event.get("id"), f"event-{index}"
        )
        if fixed or external:
            constraints.append(
                ExperienceItem(
                    item_id=item_id,
                    title=f"保留日历安排：{title}。",
                    reason_code=(
                        "fixed_calendar_event"
                        if explicitly_fixed or not external
                        else "external_commitment"
                    ),
                    before=_event_snapshot(event),
                    after=_event_snapshot(event),
                )
            )
        else:
            suggestions.append(
                ExperienceItem(
                    item_id=item_id,
                    title=f"可灵活安排日历时段：{title}。",
                    reason_code="flexible_calendar_event",
                )
            )
    return constraints, suggestions


def _task_items(
    tasks: list[dict[str, Any]],
    target_date: str | None,
    *,
    low_energy: bool,
    events: list[dict[str, Any]],
) -> tuple[
    list[ExperienceItem],
    list[ExperienceItem],
    list[ExperienceItem],
    list[ExperienceItem],
]:
    constraints: list[ExperienceItem] = []
    suggestions: list[ExperienceItem] = []
    adjustments: list[ExperienceItem] = []
    confirmations: list[ExperienceItem] = []
    for index, task in enumerate(tasks, start=1):
        title = _item_title(task)
        due = _due_date(task)
        due_today = target_date is not None and _due_day(due) == target_date
        forced = task.get("forced_deadline") is True
        external_commitment = (
            task.get("external_commitment") is True
            or task.get("affects_commitment") is True
        )
        fixed_task = task.get("fixed_meeting") is True
        if external_commitment or fixed_task or forced or due_today:
            constraints.append(
                ExperienceItem(
                    item_id=_safe_item_id(task.get("task_guid") or task.get("item_id"), f"deadline-{index}"),
                    title=(
                        f"保留外部承诺：{title}。"
                        if external_commitment
                        else f"保留截止任务：{title}。"
                    ),
                    reason_code=(
                        "external_commitment"
                        if external_commitment
                        else "fixed_task"
                        if fixed_task
                        else "forced_deadline"
                        if forced
                        else "due_today"
                    ),
                    before=_task_snapshot(task),
                    after=_task_snapshot(task),
                )
            )
        priority = str(task.get("priority", "")).upper()
        if due_today or priority.startswith(("P0", "P1")):
            suggestions.append(
                ExperienceItem(
                    item_id=_safe_item_id(task.get("task_guid") or task.get("item_id"), f"priority-{index}"),
                    title=f"优先考虑：{title}。",
                    reason_code="due_today_task" if due_today else "high_priority_task",
                )
            )
        old_start = task.get("start") or task.get("start_at")
        new_start = task.get("suggested_start")
        safe_to_adjust = task.get("movable") is True and not any(
            (external_commitment, fixed_task, forced, due_today)
        )
        reason_code = None
        if (
            safe_to_adjust
            and isinstance(old_start, str)
            and isinstance(new_start, str)
            and old_start != new_start
        ):
            rescheduled = _rescheduled_snapshot(task, new_start, events, tasks)
            if rescheduled is None:
                before = _task_snapshot(task)
                confirmations.append(
                    ExperienceItem(
                        item_id=_safe_item_id(
                            task.get("task_guid") or task.get("item_id"),
                            f"unsafe-{index}",
                        ),
                        title=f"建议时段可能冲突，暂不调整：{title}。",
                        reason_code="unsafe_suggested_start",
                        before=before,
                        after=before,
                        requires_confirmation=True,
                    )
                )
            else:
                reason_code = "movable_task_rescheduled_in_draft"
        elif (
            safe_to_adjust
            and low_energy
            and task.get("work_mode") == "deep"
            and task.get("downgrade_allowed") is True
        ):
            reason_code = "low_energy_deep_work_downgraded"
        if reason_code is not None:
            before = _task_snapshot(task)
            after = (
                rescheduled
                if reason_code == "movable_task_rescheduled_in_draft"
                else dict(before)
            )
            if reason_code == "movable_task_rescheduled_in_draft":
                title_prefix = "草案中建议调整"
            else:
                after["work_mode"] = "light"
                title_prefix = "低能量日草案中建议降为轻量"
            adjustments.append(
                ExperienceItem(
                    item_id=_safe_item_id(task.get("task_guid") or task.get("item_id"), f"move-{index}"),
                    title=f"{title_prefix}：{title}。",
                    reason_code=reason_code,
                    before=before,
                    after=after,
                )
            )
        elif safe_to_adjust and not any(
            item.item_id
            == _safe_item_id(task.get("task_guid") or task.get("item_id"), f"priority-{index}")
            for item in suggestions
        ):
            suggestions.append(
                ExperienceItem(
                    item_id=_safe_item_id(task.get("task_guid") or task.get("item_id"), f"movable-{index}"),
                    title=f"可灵活安排：{title}。",
                    reason_code="movable_task_available",
                )
            )
    return constraints, suggestions, adjustments, confirmations


def _energy_deadline_confirmations(
    tasks: list[dict[str, Any]], target_date: str | None
) -> list[ExperienceItem]:
    result: list[ExperienceItem] = []
    for index, task in enumerate(tasks, start=1):
        deadline_today = (
            target_date is not None
            and _due_day(_due_date(task)) == target_date
        ) or task.get("forced_deadline") is True
        high_effort = task.get("is_tough") is True or str(
            task.get("energy_requirement", task.get("energy", ""))
        ).casefold() in {"high", "deep", "high_energy", "高"}
        if not (deadline_today and high_effort):
            continue
        title = _item_title(task)
        result.append(
            ExperienceItem(
                item_id=_safe_item_id(task.get("task_guid") or task.get("item_id"), f"confirm-{index}"),
                title=f"截止任务「{title}」与低能量建议冲突，请确认优先策略。",
                reason_code="deadline_energy_conflict",
                requires_confirmation=True,
            )
        )
    return result


def _is_low_energy(energy: Mapping[str, Any]) -> bool:
    score = energy.get("body_battery_score")
    sleep = energy.get("sleep_hours")
    mental = str(energy.get("mental_state", "")).casefold()
    load = str(energy.get("study_load", "")).casefold()
    return (
        (type(score) in {int, float} and score <= 35)
        or (type(sleep) in {int, float} and sleep < 6)
        or mental in {"depleted", "exhausted", "低落", "疲惫"}
        or load in {"recovery", "恢复", "恢复优先"}
    )


def _event_snapshot(event: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source, target in (
        ("start", "start"),
        ("start_time", "start"),
        ("end", "end"),
        ("end_time", "end"),
        ("summary", "title"),
        ("title", "title"),
    ):
        if source in event and target not in result:
            result[target] = event[source]
    return result


def _task_snapshot(task: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"title": _item_title(task)}
    for source, target in (
        ("start", "start"),
        ("start_at", "start"),
        ("end", "end"),
        ("end_at", "end"),
        ("deadline", "deadline"),
        ("due_at", "deadline"),
        ("priority", "priority"),
        ("work_mode", "work_mode"),
    ):
        if source in task and target not in result:
            result[target] = task[source]
    return result


def _rescheduled_snapshot(
    task: Mapping[str, Any],
    suggested_start: str,
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    old_start = _aware_datetime(task.get("start", task.get("start_at")))
    old_end = _aware_datetime(task.get("end", task.get("end_at")))
    new_start = _aware_datetime(suggested_start)
    if (
        old_start is None
        or old_end is None
        or new_start is None
        or old_end <= old_start
    ):
        return None
    new_end = new_start + (old_end - old_start)
    deadline = _deadline_datetime(
        task.get("deadline", task.get("due_at")), new_start
    )
    if deadline is not None and new_end > deadline:
        return None

    for event in events:
        is_hard = (
            event.get("fixed_meeting") is True
            or event.get("external_commitment") is True
            or event.get("affects_commitment") is True
            or event.get("movable") is not True
        )
        if is_hard and _overlaps_mapping(new_start, new_end, event):
            return None

    task_id = task.get("task_guid", task.get("item_id"))
    for other in tasks:
        other_id = other.get("task_guid", other.get("item_id"))
        if other is task or (task_id is not None and other_id == task_id):
            continue
        if _overlaps_mapping(new_start, new_end, other):
            return None

    after = _task_snapshot(task)
    after["start"] = new_start.isoformat()
    after["end"] = new_end.isoformat()
    return after


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(
            value.replace("/", "-").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _deadline_datetime(value: Any, reference: datetime) -> datetime | None:
    parsed = _aware_datetime(value)
    if parsed is not None:
        return parsed
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value.replace("/", "-"))
    except ValueError:
        return None
    return datetime.combine(day, time.max, tzinfo=reference.tzinfo)


def _overlaps_mapping(
    start: datetime, end: datetime, item: Mapping[str, Any]
) -> bool:
    other_start = _aware_datetime(item.get("start", item.get("start_at")))
    other_end = _aware_datetime(item.get("end", item.get("end_at")))
    return (
        other_start is not None
        and other_end is not None
        and start < other_end
        and other_start < end
    )


def _item_title(item: Mapping[str, Any]) -> str:
    for field in ("summary", "title", "name"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _due_date(task: Mapping[str, Any]) -> str | None:
    value = task.get("deadline", task.get("due_at"))
    return value if isinstance(value, str) and value.strip() else None


def _due_day(value: str | None) -> str | None:
    if value is None:
        return None
    date_text = value[:10].replace("/", "-")
    try:
        return date.fromisoformat(date_text).isoformat()
    except ValueError:
        return None


def _safe_item_id(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        normalized = "".join(
            char if char.isascii() and (char.isalnum() or char in "_.:-") else "-"
            for char in value.casefold()
        )
        if normalized and normalized[0].isascii() and normalized[0].islower():
            return normalized[:128]
    return fallback


def _safe_reason(value: Any) -> str:
    if isinstance(value, str) and _SAFE_REASON.fullmatch(value):
        return value[:128]
    return "source_unavailable"


def _source_unavailable_title(step_id: str) -> str:
    return {
        "today-calendar": "日历安排暂不可用。",
        "today-tasks": "任务信息暂不可用。",
        "today-energy": "身体能量信息暂不可用。",
    }.get(step_id, "今日所需数据暂不可用。")
