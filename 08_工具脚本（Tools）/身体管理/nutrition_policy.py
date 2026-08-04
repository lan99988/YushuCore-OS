"""Minimum viable Body OS nutrition policy."""

from __future__ import annotations

from typing import Any


DEFAULT_BODY_WEIGHT_KG = 70.0


def derive_nutrition_policy(
    *,
    body_weight_kg: float | int | None = None,
    goal_priority: list[str] | None = None,
    training_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weight = float(body_weight_kg or DEFAULT_BODY_WEIGHT_KG)
    protein_target = int(round(weight * 1.8))
    hints: list[dict[str, str]] = []
    if training_context and training_context.get("training_load") in ("normal", "caution", "deload"):
        hints.append(
            {
                "code": "training_day_protein",
                "message": "训练日前后优先补足蛋白质，单餐可安排25-40g优质蛋白。",
            }
        )

    return {
        "mode": "minimum_loop",
        "uses_food_database": False,
        "body_weight_kg": weight,
        "protein_target_g": protein_target,
        "water_target_ml": int(round(weight * 35)),
        "goal_priority": goal_priority or ["recomposition", "fat_loss", "muscle_gain"],
        "hints": hints,
        "recommendation": (
            f"暂不使用复杂食物数据库；今天先抓蛋白质 {protein_target}g 左右，"
            "再保证饮水和训练后补充。"
        ),
    }
