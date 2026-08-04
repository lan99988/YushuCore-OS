from __future__ import annotations

from runtime_core.models import ModelRoute


class ModelRouter:
    _CLOUD_COMPLEXITIES = {"complex", "deep", "high"}
    _LOCAL_ONLY_SENSITIVITIES = {"level_3", "level_4"}

    def __init__(self, *, local_model: str, cloud_model: str) -> None:
        self.local_model = local_model
        self.cloud_model = cloud_model

    def select(
        self,
        *,
        complexity: str,
        network_mode: str,
        max_context_sensitivity: str = "level_0",
    ) -> ModelRoute:
        normalized_mode = network_mode.upper()
        normalized_complexity = complexity.lower()
        if max_context_sensitivity in self._LOCAL_ONLY_SENSITIVITIES:
            return ModelRoute(
                provider="local",
                model_name=self.local_model,
                reason="sensitive_context_requires_local_model",
            )
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
