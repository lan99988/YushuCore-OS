from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import re
from typing import Any

from orchestration import FlowName, UserIntent

from experience_layer.contracts import (
    ExperienceItem,
    ExperienceRequest,
    ExperienceResponse,
)
from personal_intelligence.models import PersonalRuleStatus, PersonalRuleTarget


class AdjustFlow:
    """Build a deterministic adjustment proposal without applying changes."""

    def __init__(self, *, rule_provider: Any = None) -> None:
        self._rule_provider = rule_provider

    def run(
        self, request: ExperienceRequest, intent: UserIntent
    ) -> ExperienceResponse:
        if not isinstance(request, ExperienceRequest):
            raise TypeError("request must be an ExperienceRequest")
        if not isinstance(intent, UserIntent):
            raise TypeError("intent must be a UserIntent")
        if intent.flow is not FlowName.ADJUST:
            raise ValueError("intent must target the Adjust flow")

        context = request.context
        energy = context.get("energy")
        if not _energy_is_fresh(energy):
            return ExperienceResponse(
                flow=FlowName.ADJUST,
                status="needs_clarification",
                uncertainties=(
                    ExperienceItem(
                        item_id="adjust-energy",
                        title="缺少新鲜的身体能量状态，暂不自动调整安排。",
                        reason_code="energy_signal_unavailable",
                        requires_confirmation=True,
                    ),
                ),
            )

        if energy.get("level") != "low":
            return ExperienceResponse(
                flow=FlowName.ADJUST,
                status="completed",
                understood=(
                    ExperienceItem(
                        item_id="adjust-energy",
                        title="当前能量状态无需重排。",
                        reason_code="no_adjustment_needed",
                    ),
                ),
            )

        items = context.get("items", ())
        candidate_slots = context.get("candidate_slots", ())
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            return _invalid_schedule_response()
        if not isinstance(candidate_slots, Sequence) or isinstance(
            candidate_slots, (str, bytes)
        ):
            return _invalid_schedule_response()
        if any(not isinstance(item, Mapping) for item in items):
            return _invalid_schedule_response()

        hard_constraints: list[ExperienceItem] = []
        suggestions: list[ExperienceItem] = []
        automatic_adjustments: list[ExperienceItem] = []
        confirmations: list[ExperienceItem] = []
        ordered_items = sorted(items, key=_item_sort_key)

        for item in ordered_items:
            item_id = str(item.get("item_id", "unknown"))
            title = _item_title(item, item_id)
            before = _state_snapshot(item)

            is_fixed = item.get("fixed_meeting") is True
            is_commitment = (
                item.get("external_commitment") is True
                or item.get("affects_commitment") is True
            )
            is_forced_deadline = item.get("forced_deadline") is True
            if is_forced_deadline:
                confirmations.append(
                    ExperienceItem(
                        item_id=_result_id(item_id),
                        title=f"{title}有强制截止；未移动，请人工决定后续安排。",
                        reason_code="forced_deadline_preserved",
                        before=before,
                        after=before,
                        requires_confirmation=True,
                    )
                )
                continue
            if is_fixed or is_commitment:
                hard_constraints.append(
                    ExperienceItem(
                        item_id=_result_id(item_id),
                        title=f"保留硬约束：{title}",
                        reason_code="fixed_commitment_preserved",
                        before=before,
                        after=before,
                    )
                )
                continue

            if item.get("item_type") != "task" or item.get("work_mode") != "deep":
                continue

            duration = _item_duration(item)
            slot = (
                _find_candidate_slot(item, duration, candidate_slots, items)
                if item.get("movable") is True and duration is not None
                else None
            )
            if slot is not None:
                start, end = slot
                after = dict(before)
                after["start"] = start.isoformat()
                after["end"] = end.isoformat()
                change = ExperienceItem(
                    item_id=_result_id(item_id),
                    title=f"建议将深度任务「{title}」移至可用时段。",
                    reason_code="low_energy_deep_work_moved",
                    before=before,
                    after=after,
                    requires_confirmation=item.get("external_calendar") is True,
                )
                if change.requires_confirmation:
                    confirmations.append(change)
                else:
                    automatic_adjustments.append(change)
                continue

            if item.get("downgrade_allowed") is True:
                after = dict(before)
                after["work_mode"] = "light"
                automatic_adjustments.append(
                    ExperienceItem(
                        item_id=_result_id(item_id),
                        title=f"建议将深度任务「{title}」降为轻量模式。",
                        reason_code="low_energy_deep_work_downgraded",
                        before=before,
                        after=after,
                    )
                )
                continue

            confirmations.append(
                ExperienceItem(
                    item_id=_result_id(item_id),
                    title=f"无法安全调整「{title}」，请决定是否改期。",
                    reason_code="no_safe_adjustment_available",
                    before=before,
                    after=before,
                    requires_confirmation=True,
                )
            )

        if (
            self._rule_provider is not None
            and not hard_constraints
            and not confirmations
            and not automatic_adjustments
        ):
            suggestions.extend(
                _personal_rule_suggestions(
                    self._rule_provider,
                    context,
                    target=PersonalRuleTarget.ADJUST,
                )
            )

        return ExperienceResponse(
            flow=FlowName.ADJUST,
            status="completed",
            hard_constraints=tuple(hard_constraints),
            suggestions=tuple(suggestions),
            confirmations=tuple(confirmations),
            # This flow only previews policy output; persistence and external
            # writes belong to a separate, authorized execution step.
            recorded=(),
            automatic_adjustments=tuple(automatic_adjustments),
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
                item_id=f"adjust-rule-{rule.rule_id}",
                title=f"个人调整建议：{rule.suggested_action}（依据：{rule.hypothesis}）",
                reason_code="personal_rule_guidance",
                rule_id=rule.rule_id,
                evidence_refs=tuple(rule.supporting_evidence),
                confidence=rule.confidence,
            )
        )
    return suggestions


def _energy_is_fresh(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("level") in {"low", "normal", "high"}
        and value.get("fresh") is True
    )


def _invalid_schedule_response() -> ExperienceResponse:
    return ExperienceResponse(
        flow=FlowName.ADJUST,
        status="needs_clarification",
        uncertainties=(
            ExperienceItem(
                item_id="adjust-schedule",
                title="当前日程数据不完整，暂不生成调整提案。",
                reason_code="schedule_snapshot_invalid",
                requires_confirmation=True,
            ),
        ),
    )


def _result_id(item_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]", "-", item_id).strip("-")[:110]
    return f"adjust-{safe or 'item'}"


def _item_title(item: Mapping[str, Any], item_id: str) -> str:
    title = item.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else item_id


def _state_snapshot(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in ("start", "end", "work_mode", "deadline")
        if key in item
    }


def _item_sort_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return (str(item.get("start", "")), str(item.get("item_id", "")))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _item_duration(item: Mapping[str, Any]) -> timedelta | None:
    start = _parse_datetime(item.get("start"))
    end = _parse_datetime(item.get("end"))
    if start is None or end is None or end <= start:
        return None
    return end - start


def _find_candidate_slot(
    item: Mapping[str, Any],
    duration: timedelta,
    candidate_slots: Sequence[Any],
    items: Sequence[Mapping[str, Any]],
) -> tuple[datetime, datetime] | None:
    candidates: list[tuple[datetime, datetime]] = []
    for candidate in candidate_slots:
        if not isinstance(candidate, Mapping):
            continue
        start = _parse_datetime(candidate.get("start"))
        end = _parse_datetime(candidate.get("end"))
        if start is None or end is None or end - start < duration:
            continue
        candidate_end = start + duration

        deadline_value = item.get("deadline")
        if deadline_value is not None:
            deadline = _parse_datetime(deadline_value)
            if deadline is None or candidate_end > deadline:
                continue

        if any(
            _overlaps(start, candidate_end, other)
            for other in items
            if other.get("item_id") != item.get("item_id")
        ):
            continue
        candidates.append((start, candidate_end))

    return min(candidates, key=lambda value: value[0]) if candidates else None


def _overlaps(start: datetime, end: datetime, item: Mapping[str, Any]) -> bool:
    other_start = _parse_datetime(item.get("start"))
    other_end = _parse_datetime(item.get("end"))
    return (
        other_start is not None
        and other_end is not None
        and start < other_end
        and other_start < end
    )
