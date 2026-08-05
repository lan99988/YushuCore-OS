from __future__ import annotations


def assess_body_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    declining = snapshot.get("recovery_trend") == "declining"
    increasing = snapshot.get("training_load_trend") == "increasing"
    return {
        "proposal_type": "training_adjustment",
        "recommended_load": "reduce" if declining and increasing else "maintain",
        "reason": "Training load is increasing while recovery is declining." if declining and increasing else "No load reduction signal.",
        "evidence": [key for key in ("training_load_trend", "recovery_trend") if key in snapshot],
        "confidence": 0.85 if declining and increasing else 0.5,
        "requires_human_review": True,
        "status": "draft",
    }
