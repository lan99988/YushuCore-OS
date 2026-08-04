"""Body OS activityType-level training policy.

This module intentionally uses only stable Garmin activity fields available in
the cleaned dataset. Muscle-group rules are left for a later exercise-set API.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any


SCOPE_NOTE = "肌群级规则已启用：手动录入训练自动判断肌群重复风险。"

# 48 小时内同一肌群重复训练的标签
MUSCLE_48H_LABEL = "muscle_group_48h_repeat"


def _parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_strength(log: dict[str, Any]) -> bool:
    return log.get("activity_type") == "strength"


def _daily_loads(training_logs: list[dict[str, Any]]) -> dict[dt.date, float]:
    loads: dict[dt.date, float] = defaultdict(float)
    for log in training_logs:
        day = _parse_date(log.get("date"))
        if day:
            loads[day] += _as_float(log.get("training_load"))
    return dict(loads)


def _strength_dates(training_logs: list[dict[str, Any]]) -> set[dt.date]:
    dates = set()
    for log in training_logs:
        day = _parse_date(log.get("date"))
        if day and _is_strength(log):
            dates.add(day)
    return dates


def _recent_strength_streak(strength_dates: set[dt.date], today: dt.date) -> int:
    streak = 0
    cursor = today - dt.timedelta(days=1)
    while cursor in strength_dates:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def _sum_window(loads: dict[dt.date, float], start: dt.date, end: dt.date) -> float:
    total = 0.0
    cursor = start
    while cursor <= end:
        total += loads.get(cursor, 0.0)
        cursor += dt.timedelta(days=1)
    return round(total, 2)


def _warning(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _muscle_groups_for_log(log: dict[str, Any]) -> list[str]:
    """从训练日志中提取肌群列表（手动录入或 Garmin 带 exercises 时有效）。"""
    mg = log.get("muscle_groups")
    if isinstance(mg, list) and len(mg) > 0:
        return [str(g) for g in mg]
    # Garmin 数据无 muscle_groups，但可通过 exercises 反推
    exercises = log.get("exercises")
    if isinstance(exercises, list) and len(exercises) > 0:
        groups: set[str] = set()
        for ex in exercises:
            g = ex.get("muscle_group") if isinstance(ex, dict) else None
            if g:
                groups.add(str(g))
        return sorted(groups)
    return []


def _check_muscle_group_repeat(
    training_logs: list[dict[str, Any]],
    today: dt.date,
) -> list[dict[str, str]]:
    """检查最近 48 小时内是否有同一肌群被训练（仅对含肌群信息的日志生效）。"""
    warnings: list[dict[str, str]] = []
    # 收集近 2 天每个日志的肌群
    recent_muscle: dict[dt.date, set[str]] = {}
    for log in training_logs:
        day = _parse_date(log.get("date"))
        if day is None:
            continue
        if today - dt.timedelta(days=2) <= day <= today - dt.timedelta(days=1):
            groups = _muscle_groups_for_log(log)
            if groups:
                recent_muscle.setdefault(day, set()).update(groups)

    # 统计最近 48h 肌群总集合（多天叠加）
    recent_groups: set[str] = set()
    for groups_set in recent_muscle.values():
        recent_groups.update(groups_set)

    if recent_groups:
        today_groups: set[str] = set()
        for log in training_logs:
            day = _parse_date(log.get("date"))
            if day == today:
                today_groups.update(_muscle_groups_for_log(log))

        repeated = recent_groups & today_groups if today_groups else recent_groups
        # 如果有今天训练数据才报同一肌群重复；若无今天数据则报"最近已训练"
        if today_groups and repeated:
            warnings.append(
                _warning(
                    MUSCLE_48H_LABEL,
                    f"肌群重复风险：{'、'.join(sorted(repeated))}"
                    " 在 48 小时内已训练过，建议换其他肌群。",
                    "warning",
                )
            )
        elif not today_groups and recent_groups:
            # 仅提示：最近 48h 练过的肌群列表（信息性）
            warnings.append(
                _warning(
                    MUSCLE_48H_LABEL,
                    f"最近 48 小时内已训练肌群：{'、'.join(sorted(recent_groups))}。"
                    " 如有今日训练计划，建议避开这些肌群。",
                    "info",
                )
            )

    return warnings


def derive_training_policy(
    training_logs: list[dict[str, Any]],
    *,
    today: str | None = None,
    energy_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive training load guidance from cleaned activityType-level logs."""
    today_date = _parse_date(today) or dt.date.today()
    logs = [log for log in training_logs if isinstance(log, dict)]
    warnings: list[dict[str, str]] = []

    strength_dates = _strength_dates(logs)
    streak = _recent_strength_streak(strength_dates, today_date)
    recent_strength = any(
        today_date - dt.timedelta(days=2) <= day <= today_date - dt.timedelta(days=1)
        for day in strength_dates
    )

    if streak >= 3:
        warnings.append(
            _warning(
                "strength_3d_streak",
                f"连续{streak}天力量训练，建议降低训练量。",
                "high",
            )
        )
    elif recent_strength:
        warnings.append(
            _warning(
                "strength_48h_repeat",
                "48小时内已有力量训练，今天如继续力量训练请降低容量并避免硬拉深蹲等高负荷动作。",
            )
        )

    loads = _daily_loads(logs)
    current_start = today_date - dt.timedelta(days=7)
    current_end = today_date - dt.timedelta(days=1)
    previous_start = today_date - dt.timedelta(days=14)
    previous_end = today_date - dt.timedelta(days=8)
    current_load = _sum_window(loads, current_start, current_end)
    previous_load = _sum_window(loads, previous_start, previous_end)
    if previous_load > 0 and current_load > previous_load * 1.4:
        warnings.append(
            _warning(
                "training_load_spike_40pct",
                f"近7日训练负荷较前7日上升超过40%（{previous_load:g} -> {current_load:g}），注意降载。",
                "high",
            )
        )

    energy_context = energy_context or {}
    body_energy = _maybe_float(energy_context.get("body_battery_score"))
    low_body_energy = (
        energy_context.get("study_load") == "recovery"
        or (body_energy is not None and body_energy < 20)
    )
    if low_body_energy:
        warnings.append(
            _warning(
                "low_body_energy_training",
                "身体可用能量偏低，今天训练建议以恢复、灵活性或低强度 Zone2 为主。",
                "high",
            )
        )

    # 肌群 48h 重复检查
    muscle_warnings = _check_muscle_group_repeat(logs, today_date)
    warnings.extend(muscle_warnings)

    # 统计今日手动录入的肌群信息（用于返回）
    today_muscle_groups: list[str] = []
    today_muscle_volume: dict[str, float] = {}
    for log in logs:
        day = _parse_date(log.get("date"))
        if day == today_date:
            mg = log.get("muscle_groups")
            if isinstance(mg, list):
                today_muscle_groups.extend(mg)
            mv = log.get("muscle_volume")
            if isinstance(mv, dict):
                for k, v in mv.items():
                    today_muscle_volume[k] = round(today_muscle_volume.get(k, 0) + float(v), 2)

    severity_rank = {"info": 0, "warning": 1, "high": 2}
    max_severity = max((severity_rank.get(item["severity"], 1) for item in warnings), default=0)
    if low_body_energy:
        training_load = "recovery"
        label = "恢复"
        recommendation = "今天身体可用能量偏低，训练建议恢复优先，避免高强度力量和速度课。"
    elif any(item["code"] == "strength_3d_streak" for item in warnings):
        training_load = "deload"
        label = "降载"
        recommendation = "今天训练建议降载，优先恢复、灵活性或 Zone2。"
    elif max_severity > 0:
        training_load = "caution"
        label = "谨慎"
        recommendation = "今天训练建议保守推进，避免继续堆高强度。"
    else:
        training_load = "normal"
        label = "正常"
        recommendation = "训练频率未触发降载规则，可按计划执行。"

    return {
        "date": today_date.isoformat(),
        "training_load": training_load,
        "training_load_label": label,
        "recommendation": recommendation,
        "warnings": warnings,
        "strength_consecutive_days": streak,
        "current_7d_training_load": current_load,
        "previous_7d_training_load": previous_load,
        "scope_note": SCOPE_NOTE,
        "today_muscle_groups": today_muscle_groups or None,
        "today_muscle_volume": today_muscle_volume or None,
        "muscle_group_risk": any(
            w.get("code") == MUSCLE_48H_LABEL and w.get("severity") == "warning"
            for w in warnings
        ),
    }
