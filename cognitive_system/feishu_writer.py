"""飞书 Base 认知资产写入器（lark-cli 通道）。

命令语法与比赛管理模块（yushu_09）实测一致：
- 新建：`lark-cli base +record-upsert --base-token X --table-id Y --json @file --as user`
- 更新：`lark-cli base +record-batch-update --json @file --as user`
  （请求体 `{"record_id_list": [...], "patch": fields}`）

字段（中英双语标签分列，用户要求）：
认知ID / 类型 / 标题 / 内容 / 标签中文 / 标签英文 / 状态 / 置信度 / 版本 /
内容哈希 / IMA状态 / IMA引用 / 创建时间

网络治理：显式发起（ASSIST 模式）才可调用；OFF 模式直接拒绝（与
integrations/base.py 的既有闸门一致）。全局默认 OFF 冻结断言不动。
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from typing import Any, Callable

from .models import COGNITIVE_TYPE_LABELS, CognitiveAsset

LarkCliRunner = Callable[[list[str], str | None], "subprocess.CompletedProcess[bytes]"]


class FeishuCapabilityError(RuntimeError):
    """飞书通道配置缺失或命令失败。"""


def build_record_fields(asset: CognitiveAsset) -> dict[str, Any]:
    """CognitiveAsset → 飞书记录字段。键名与认知资产表字段一一对应。"""
    zh_label, en_label = COGNITIVE_TYPE_LABELS[asset.cognitive_type]
    return {
        "认知ID": asset.cognitive_id,
        "类型": f"{zh_label} {en_label}",
        "标题": asset.title,
        "内容": asset.statement,
        "标签中文": list(asset.tag_zh),
        "标签英文": list(asset.tag_en),
        "状态": asset.cognitive_status,
        "置信度": asset.confidence,
        "版本": asset.version,
        "内容哈希": asset.content_hash,
        "IMA状态": asset.ima_status,
        "IMA引用": asset.ima_ref,
        "创建时间": asset.created_at,
    }


def _default_runner(args: list[str], json_input: str | None) -> "subprocess.CompletedProcess[bytes]":
    """lark-cli 运行器（模式取自 02_执行引擎/输入解析引擎/lark_bridge.py）。

    lark-cli 位置：`C:\\Users\\26326\\.workbuddy\\binaries\\node\\cli-connector-packages\\lark-cli`
    或 PATH 中的 `lark-cli`。
    """
    def try_decode(data: bytes | None) -> str:
        if data is None:
            return ""
        for encoding in ("utf-8", "gbk", "cp936"):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")

    cli = os.environ.get("LARK_CLI_PATH", "")
    if not cli:
        candidate = r"C:\Users\26326\.workbuddy\binaries\node\cli-connector-packages\lark-cli"
        cli = candidate if os.path.isfile(candidate) else "lark-cli"

    tmp_path: str | None = None
    args = list(args)
    if json_input is not None:
        tmp_name = f"_lark_tmp_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(json_input)
        if "--json" in args:
            index = args.index("--json")
            if index + 1 < len(args):
                args[index + 1] = f"@{tmp_name}"

    cli_path = cli.replace("\\", "/")
    command = " ".join([f'"{cli_path}"'] + [f'"{arg}"' for arg in args])
    bash_candidates = [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        "bash",
    ]
    last_error: Exception | None = None
    try:
        for bash in bash_candidates:
            try:
                result = subprocess.run([bash, "-c", command], capture_output=True, timeout=30)
                result.stdout = try_decode(result.stdout)  # type: ignore[assignment]
                result.stderr = try_decode(result.stderr)  # type: ignore[assignment]
                return result
            except (FileNotFoundError, OSError) as exc:
                last_error = exc
                continue
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    raise FeishuCapabilityError(f"lark-cli 不可用: {last_error}")


class FeishuCognitiveWriter:
    """飞书侧持久化实现。capability：增 ✅ / 改 ✅（真更新）/ 删 ✅（API 支持，本层暂不暴露）。"""

    name = "feishu"
    supports_update = True
    supports_delete = True

    def __init__(
        self,
        *,
        base_token: str,
        table_id: str,
        runner: LarkCliRunner | None = None,
        network_mode: str = "ASSIST",
    ) -> None:
        if not base_token or not table_id:
            raise FeishuCapabilityError(
                "缺少 base_token / table_id 配置。请在 config/cognitive.yaml 登记认知资产表后再启用飞书双写。"
            )
        if network_mode.upper() == "OFF":
            raise FeishuCapabilityError("feishu integration is disabled in OFF mode")
        self._base_token = base_token
        self._table_id = table_id
        self._runner: LarkCliRunner = runner or _default_runner

    # ---------------------------------------------------------------- 内部

    def _run(self, args: list[str], payload: Any | None = None) -> dict[str, Any]:
        json_input = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        result = self._runner(args, json_input)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        code = getattr(result, "returncode", 1)
        if code != 0:
            raise FeishuCapabilityError(f"lark-cli 失败({code}): {stderr or stdout[:300]}")
        try:
            decoded = json.loads(stdout)
        except ValueError:
            return {"raw": stdout}
        return decoded if isinstance(decoded, dict) else {"data": decoded}

    # ---------------------------------------------------------------- 写入

    def write(self, asset: CognitiveAsset) -> dict[str, Any]:
        """新建记录。upsert 语义天然幂等：同 cognitive_id 重复写不会产生第二条。"""
        if not asset.cognitive_id:
            raise ValueError("asset.cognitive_id 未分配，拒绝写入飞书")
        payload = build_record_fields(asset)
        response = self._run(
            [
                "base", "+record-upsert",
                "--base-token", self._base_token,
                "--table-id", self._table_id,
                "--json", "@_record_json",
                "--as", "user",
            ],
            payload,
        )
        record_id = self._extract_record_id(response)
        return {
            "status": "synced",
            "ref": record_id or asset.cognitive_id,
            "remote_hash": asset.content_hash,
            "extra": {"response_keys": sorted(response.keys())},
        }

    def update(self, asset: CognitiveAsset) -> dict[str, Any]:
        """更新记录（飞书支持真更新；IMA 侧对应 append-only 事件）。"""
        if not asset.feishu_ref:
            raise ValueError("asset.feishu_ref 为空，无法更新（应先 write）")
        payload = {"record_id_list": [asset.feishu_ref], "patch": build_record_fields(asset)}
        response = self._run(
            [
                "base", "+record-batch-update",
                "--base-token", self._base_token,
                "--table-id", self._table_id,
                "--json", "@_record_json",
                "--as", "user",
            ],
            payload,
        )
        return {"status": "synced", "ref": asset.feishu_ref, "remote_hash": asset.content_hash, "extra": {"response_keys": sorted(response.keys())}}

    # ---------------------------------------------------------------- 检索

    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """按认知ID/标题检索记录（+record-list 后本地过滤；一期可接受）。"""
        response = self._run(
            [
                "base", "+record-list",
                "--base-token", self._base_token,
                "--table-id", self._table_id,
                "--as", "user",
                "--limit", str(max(limit, 1)),
                "--format", "json",
            ],
            None,
        )
        records = response.get("data") or response.get("records") or []
        if isinstance(records, dict):
            records = records.get("items") or []
        needle = query.strip().casefold()
        hits: list[dict[str, Any]] = []
        for record in records if isinstance(records, list) else []:
            fields = record.get("fields", {}) if isinstance(record, dict) else {}
            flattened = json.dumps(fields, ensure_ascii=False).casefold()
            if needle in flattened:
                hits.append(record)
        return hits

    @staticmethod
    def _extract_record_id(response: dict[str, Any]) -> str:
        for key_path in (("record_id",), ("record", "record_id"), ("data", "record_id"), ("data", "record", "record_id")):
            cursor: Any = response
            for key in key_path:
                if not isinstance(cursor, dict) or key not in cursor:
                    break
                cursor = cursor[key]
            else:
                if isinstance(cursor, str) and cursor:
                    return cursor
                if isinstance(cursor, dict) and isinstance(cursor.get("record_id"), str):
                    return cursor["record_id"]
        return ""
