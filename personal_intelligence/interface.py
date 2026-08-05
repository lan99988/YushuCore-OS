from __future__ import annotations

from typing import Any

from .models import ModelDescriptor, ModelRoute


class PersonalModelInterface:
    """Versioned analysis boundary; training is intentionally unavailable."""

    def describe_model(self) -> ModelDescriptor:
        return ModelDescriptor()

    def select_route(self, *, sensitivity: str, network_mode: str) -> ModelRoute:
        if sensitivity not in {"level_0", "level_1", "level_2", "level_3", "level_4"}:
            raise ValueError("invalid sensitivity")
        if network_mode not in {"OFF", "ASSIST", "SYNC"}:
            raise ValueError("invalid network mode")
        return ModelRoute(
            provider="local",
            reason="Personal Intelligence is local-first and high-sensitivity safe.",
            max_sensitivity="level_2",
        )

    def analyze(self, context: Any, *, prompt_version: str = "0.1", policy_version: str = "0.1") -> dict[str, object]:
        return {
            "status": "analysis_only",
            "context": context,
            "prompt_version": prompt_version,
            "policy_version": policy_version,
            "proposals": (),
        }

    def train(self, dataset: Any) -> None:
        raise NotImplementedError("Personal Model training is not enabled in Phase 5")
