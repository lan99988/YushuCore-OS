from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from runtime_core.router import ModelRouter


VALID_NETWORK_MODES = {"OFF", "ASSIST", "SYNC"}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry max_attempts must be at least 1")


@dataclass(frozen=True)
class RuntimePolicy:
    network_mode: str
    local_model: str
    cloud_model: str
    retry: RetryPolicy = RetryPolicy()

    def __post_init__(self) -> None:
        if self.network_mode not in VALID_NETWORK_MODES:
            raise ValueError("network_mode must be OFF, ASSIST, or SYNC")
        if not self.local_model.strip():
            raise ValueError("local_model is required")
        if not self.cloud_model.strip():
            raise ValueError("cloud_model is required")

    def model_router(self) -> ModelRouter:
        return ModelRouter(local_model=self.local_model, cloud_model=self.cloud_model)

    @classmethod
    def with_retry(
        cls,
        *,
        network_mode: str,
        local_model: str,
        cloud_model: str,
        retry_max_attempts: int,
    ) -> "RuntimePolicy":
        return cls(
            network_mode=network_mode,
            local_model=local_model,
            cloud_model=cloud_model,
            retry=RetryPolicy(max_attempts=retry_max_attempts),
        )


def load_runtime_policy(config_dir: str | Path) -> RuntimePolicy:
    root = Path(config_dir)
    network_config = yaml.safe_load((root / "network.yaml").read_text(encoding="utf-8")) or {}
    model_config = yaml.safe_load((root / "model.yaml").read_text(encoding="utf-8")) or {}
    runtime_path = root / "runtime.yaml"
    runtime_config = yaml.safe_load(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else {}
    runtime_config = runtime_config or {}
    retry_config = runtime_config.get("retry", {}) or {}
    network_mode = network_config.get("network_mode", "OFF")
    if network_mode is False:
        network_mode = "OFF"
    return RuntimePolicy(
        network_mode=str(network_mode).upper(),
        local_model=str(model_config.get("local_model", "")),
        cloud_model=str(model_config.get("cloud_model", "")),
        retry=RetryPolicy(max_attempts=int(retry_config.get("max_attempts", 1))),
    )
