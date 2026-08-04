"""Body OS recovery policy."""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _warning(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def derive_recovery_policy(
    energy_context: dict[str, Any] | None,
    training_context: dict[str, Any] | None,
) -> dict[str, Any]:
    energy_context = energy_context or {}
    training_context = training_context or {}
    body_energy = _num(energy_context.get("body_battery_score", energy_context.get("body_battery")))
    sleep_hours = _num(energy_context.get("sleep_hours"))
    stress = _num(energy_context.get("stress_level"))
    training_load = training_context.get("training_load")

    warnings: list[dict[str, str]] = []
    if body_energy is not None and body_energy < 20:
        warnings.append(_warning("low_body_energy", "身体可用能量偏低，今天优先保护恢复。", "high"))
    if sleep_hours is not None and sleep_hours < 6:
        warnings.append(_warning("low_sleep", "睡眠不足6小时，降低训练与高认知负荷。", "high"))
    if stress is not None and stress >= 65:
        warnings.append(_warning("high_stress", "压力偏高，适合低强度恢复。"))
    if training_load in ("caution", "deload", "recovery"):
        warnings.append(_warning("training_risk", "训练侧已触发保守或降载建议。"))

    if any(item["code"] == "low_body_energy" for item in warnings):
        state = "protect"
        recommended = "recovery"
        label = "保护恢复"
    elif any(item["severity"] == "high" for item in warnings):
        state = "strained"
        recommended = "deload"
        label = "恢复不足"
    else:
        state = "ready"
        recommended = "normal"
        label = "可训练"

    return {
        "recovery_state": state,
        "recovery_label": label,
        "recommended_training": recommended,
        "warnings": warnings,
        "recommendation": (
            "保护恢复：以睡眠、散步、拉伸和低强度 Zone2 为主。"
            if state == "protect"
            else "恢复不足：训练降载，避免堆高强度。"
            if state == "strained"
            else "恢复状态可接受，可按计划执行并保留休息。"
        ),
    }
