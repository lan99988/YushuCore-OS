from __future__ import annotations

from runtime_core.models import ModelRoute


class ModelRouter:
    _CLOUD_COMPLEXITIES = {"complex", "deep", "high"}

    def __init__(self, *, local_model: str, cloud_model: str) -> None:
        self.local_model = local_model
        self.cloud_model = cloud_model

    def select(self, *, complexity: str, network_mode: str) -> ModelRoute:
        normalized_mode = network_mode.upper()
        normalized_complexity = complexity.lower()
        if (
            normalized_mode in {"ASSIST", "SYNC"}
            and normalized_complexity in self._CLOUD_COMPLEXITIES
        ):
            return ModelRoute(
                provider="cloud",
                model_name=self.cloud_model,
                reason="complex_task_with_network_enabled",
            )
        return ModelRoute(
            provider="local",
            model_name=self.local_model,
            reason="local_first",
        )
