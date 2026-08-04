"""Body OS energy policy.

Turns Garmin-derived Energy fields into study load and task-carrying guidance.
Body Battery is represented as ``body_battery_score`` and means 身体可用能量:
physical recovery state plus task-carrying capacity, not a direct mood reading.
"""

from __future__ import annotations

from typing import Any


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float | None) -> str:
    if value is None:
        return "缺失"
    if value.is_integer():
        return str(int(value))
    return str(round(value, 2))


def derive_daily_mental_state(energy: dict[str, Any]) -> dict[str, Any]:
    """Derive mental-state labels and study load from Energy fields."""
    battery = _as_float(
        energy.get("body_battery_score", energy.get("body_battery"))
    )
    readiness = _as_float(energy.get("readiness_score"))
    sleep_hours = _as_float(energy.get("sleep_hours"))
    stress = _as_float(energy.get("stress_level"))

    reason_parts = []
    if battery is not None:
        reason_parts.append(f"身体可用能量{_format_number(battery)}")
    if readiness is not None:
        reason_parts.append(f"准备度{_format_number(readiness)}")
    if sleep_hours is not None:
        reason_parts.append(f"睡眠{_format_number(sleep_hours)}小时")
    if stress is not None:
        reason_parts.append(f"压力{_format_number(stress)}")
    reason = "，".join(reason_parts) if reason_parts else "Garmin 有效统计不足"

    if battery is not None and battery < 20:
        return {
            "mental_state": "depleted",
            "mental_state_label": "耗竭",
            "level": "极低",
            "status": "差",
            "study_load": "recovery",
            "study_load_label": "恢复/维护",
            "task_policy": "只安排维护型任务、轻复盘和必要事务，避免高认知硬任务。",
            "energy_coefficient": 0.65,
            "reason": f"{reason}，身体可用能量低于20，今天先保护恢复。",
        }

    low_signals = [
        battery is not None and battery < 40,
        sleep_hours is not None and sleep_hours < 6,
        readiness is not None and readiness < 45,
        stress is not None and stress >= 65,
    ]
    if any(low_signals):
        return {
            "mental_state": "low",
            "mental_state_label": "偏低",
            "level": "低",
            "status": "差",
            "study_load": "light",
            "study_load_label": "轻负载",
            "task_policy": "减少深度学习，优先复习、整理、低阻力推进和短时段事务。",
            "energy_coefficient": 0.8,
            "reason": f"{reason}，至少一个恢复信号偏低。",
        }

    high_signals = [
        battery is not None and battery >= 70,
        readiness is not None and readiness >= 65,
        sleep_hours is not None and sleep_hours >= 7,
        stress is None or stress < 60,
    ]
    if all(high_signals):
        return {
            "mental_state": "high",
            "mental_state_label": "充沛",
            "level": "高",
            "status": "好",
            "study_load": "deep",
            "study_load_label": "深度学习",
            "task_policy": "可安排高认知学习、硬骨头任务和需要连续专注的事务。",
            "energy_coefficient": 1.15,
            "reason": f"{reason}，恢复信号支持高认知负载。",
        }

    return {
        "mental_state": "normal",
        "mental_state_label": "正常",
        "level": "中",
        "status": "一般",
        "study_load": "standard",
        "study_load_label": "标准负载",
        "task_policy": "按标准学习计划推进，保留休息缓冲，不额外加码。",
        "energy_coefficient": 1.0,
        "reason": f"{reason}，适合按标准节奏推进。",
    }
