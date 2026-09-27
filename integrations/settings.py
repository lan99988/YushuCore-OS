"""集成层配置解析。

职责：把 `config/network.yaml`（全局闸门）与 `config/integrations.yaml`（逐适配器声明）
收敛成适配器可用的取值。**不做任何网络调用。**

凭证优先级：环境变量 → 本地配置文件（`config/ima.local.yaml`，已被 .gitignore 覆盖）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_CONFIG = PROJECT_ROOT / "config" / "network.yaml"
INTEGRATIONS_CONFIG = PROJECT_ROOT / "config" / "integrations.yaml"
IMA_LOCAL_CONFIG = PROJECT_ROOT / "config" / "ima.local.yaml"

NETWORK_MODES = ("OFF", "assist", "sync")

IMA_CLIENT_ID_ENV = "IMA_OPENAPI_CLIENTID"
IMA_API_KEY_ENV = "IMA_OPENAPI_APIKEY"


class IntegrationConfigError(RuntimeError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IntegrationConfigError(f"无法解析配置文件 {path}: {exc}") from exc
    return loaded if isinstance(loaded, dict) else {}


def _normalize_mode(value: Any) -> str:
    # YAML 会把裸 OFF 解析为布尔 False（同理 ON/YES/NO 也是布尔）。
    # `scripts/health_check.py` 已有同样兜底，此处保持一致，避免两边解释不同。
    if value is False:
        return "OFF"
    text = str(value or "").strip()
    for mode in NETWORK_MODES:
        if text.casefold() == mode.casefold():
            return mode
    raise IntegrationConfigError(f"非法 network_mode: {value!r}（允许 {NETWORK_MODES}）")


def global_network_mode() -> str:
    """全局网络闸门。缺省仍是 OFF（安全默认）。"""
    data = _read_yaml(NETWORK_CONFIG)
    return _normalize_mode(data.get("network_mode", "OFF"))


def adapter_settings(name: str) -> dict[str, Any]:
    data = _read_yaml(INTEGRATIONS_CONFIG)
    integrations = data.get("integrations")
    if not isinstance(integrations, dict):
        return {}
    entry = integrations.get(name)
    return dict(entry) if isinstance(entry, dict) else {}


def resolve_network_mode(name: str) -> str:
    """逐适配器声明优先；未声明则回落全局闸门。

    `config/network.yaml` 的 `OFF` 是**项目默认值**，且被 `scripts/verify.py` 以
    「default network mode must be OFF」冻结断言保护。因此启用某个外部集成**不得**通过
    放宽全局默认来实现，必须走「显式声明 + `enabled: true` + 指定 mode」这条路径，
    使其成为一个**可审计的具名例外**，而默认值始终是拒绝。

    规则：
    - 未声明 或 未 enabled → 取全局闸门（当前为 OFF）
    - 已 enabled 且声明 mode → 取声明的 mode
    """
    settings = adapter_settings(name)
    if settings.get("enabled") is True and settings.get("network_mode"):
        return _normalize_mode(settings["network_mode"])
    return global_network_mode()


def ima_credentials() -> tuple[str, str]:
    """返回 (client_id, api_key)。缺失时抛错，**不静默降级**。"""
    client_id = os.environ.get(IMA_CLIENT_ID_ENV, "").strip()
    api_key = os.environ.get(IMA_API_KEY_ENV, "").strip()
    if client_id and api_key:
        return client_id, api_key
    data = _read_yaml(IMA_LOCAL_CONFIG)
    client_id = client_id or str(data.get("client_id", "")).strip()
    api_key = api_key or str(data.get("api_key", "")).strip()
    if not (client_id and api_key):
        raise IntegrationConfigError(
            "缺少 IMA 凭证。请到 https://ima.qq.com/agent-interface 生成 Client ID 与 API Key，"
            f"然后写入环境变量 {IMA_CLIENT_ID_ENV} / {IMA_API_KEY_ENV}，"
            f"或写入本地配置 {IMA_LOCAL_CONFIG}（该文件不应提交到 Git）。"
        )
    return client_id, api_key
