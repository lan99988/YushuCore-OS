from __future__ import annotations


def assess_body_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    declining = snapshot.get("recovery_trend") == "declining"
    increasing = snapshot.get("training_load_trend") == "increasing"
    low_sleep = float(snapshot.get("sleep_hours", 8) or 8) < 6
    high_fatigue = float(snapshot.get("subjective_fatigue", 0) or 0) >= 7
    reduce_load = declining and increasing
    risk_flags = []
    if low_sleep:
        risk_flags.append("low_sleep")
    if high_fatigue:
        risk_flags.append("high_subjective_fatigue")
    if reduce_load:
        risk_flags.append("load_recovery_mismatch")
    return {
        "proposal_type": "training_adjustment",
        "recommended_load": "reduce" if reduce_load else "maintain",
        "training_suggestion": "reduce" if reduce_load else "maintain",
        "recovery_suggestion": "prioritize recovery and sleep" if declining or low_sleep else "maintain current recovery plan",
        "risk_flags": risk_flags,
        "trend_analysis": {
            "training_load_trend": snapshot.get("training_load_trend"),
            "recovery_trend": snapshot.get("recovery_trend"),
        },
        "reason": "Training load is increasing while recovery is declining." if reduce_load else "No load reduction signal.",
        "evidence": [key for key in ("training_load_trend", "recovery_trend") if key in snapshot],
        "confidence": 0.85 if reduce_load else 0.5,
        "requires_human_review": True,
        "status": "draft",
    }
