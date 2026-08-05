from __future__ import annotations

from pathlib import Path

import yaml


def check_config(config_dir: str | Path) -> dict[str, object]:
    root = Path(config_dir)
    required = ("system.yaml", "model.yaml", "network.yaml", "runtime.yaml", "permission.yaml")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing config files: {', '.join(missing)}")
    system = yaml.safe_load((root / "system.yaml").read_text(encoding="utf-8")) or {}
    network = yaml.safe_load((root / "network.yaml").read_text(encoding="utf-8")) or {}
    network_mode = network.get("network_mode", "OFF")
    if network_mode is False:
        network_mode = "OFF"
    return {
        "network_mode": str(network_mode).upper(),
        "markdown_first": bool(system.get("markdown_first", False)),
        "local_first": bool(system.get("local_first", False)),
        "missing": missing,
    }
