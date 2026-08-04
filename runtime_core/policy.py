from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from runtime_core.router import ModelRouter


VALID_NETWORK_MODES = {"OFF", "ASSIST", "SYNC"}


@dataclass(frozen=True)
class RuntimePolicy:
    network_mode: str
    local_model: str
    cloud_model: str

    def __post_init__(self) -> None:
        if self.network_mode not in VALID_NETWORK_MODES:
            raise ValueError("network_mode must be OFF, ASSIST, or SYNC")
        if not self.local_model.strip():
            raise ValueError("local_model is required")
        if not self.cloud_model.strip():
            raise ValueError("cloud_model is required")

    def model_router(self) -> ModelRouter:
        return ModelRouter(local_model=self.local_model, cloud_model=self.cloud_model)


def load_runtime_policy(config_dir: str | Path) -> RuntimePolicy:
    root = Path(config_dir)
    network_config = yaml.safe_load((root / "network.yaml").read_text(encoding="utf-8")) or {}
    model_config = yaml.safe_load((root / "model.yaml").read_text(encoding="utf-8")) or {}
    network_mode = network_config.get("network_mode", "OFF")
    if network_mode is False:
        network_mode = "OFF"
    return RuntimePolicy(
        network_mode=str(network_mode).upper(),
        local_model=str(model_config.get("local_model", "")),
        cloud_model=str(model_config.get("cloud_model", "")),
    )
