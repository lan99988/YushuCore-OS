"""
飞书写入层

职责：接收 record 字段 → 调用 lark_bridge 写入飞书。
不负责解析、不负责字段生成。

迁移来源：input_parser.py 行 860-903，逻辑 100% 保留，
原全局符号改为本包内显式导入（config / lark_bridge / validators）。
"""

import json

from .config import BASE_TOKEN, TABLES
from .lark_bridge import _run_lark_cli
from .validators import deduplicate_check


def insert_to_feishu(table_name, record_fields, target_date=None, dry_run=False):
    """通过 lark-cli 写入飞书多维表格（含去重逻辑）

    Args:
        table_name: 表名
        record_fields: 字段字典
        target_date: 目标日期，用于执行库去重检查
    """
    table_id = TABLES.get(table_name)
    if not table_id:
        return {"ok": False, "error": f"Unknown table: {table_name}"}

    # 过滤空值
    fields = {k: v for k, v in record_fields.items() if v is not None and v != ""}

    # 执行库去重检查
    if target_date and deduplicate_check(table_name, fields.get("标题", ""), target_date, dry_run):
        return {"ok": True, "deduplicated": True, "table": table_name, "title": fields.get("标题")}

    if dry_run:
        return {"ok": True, "dry_run": True, "table": table_name, "payload": fields}

    # record-upsert 直接传 Map<fieldName, CellValue>，不包装 fields
    json_str = json.dumps(fields, ensure_ascii=False)

    args = [
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", table_id,
        "--json", "@_record_json",
        "--as", "user",
    ]

    try:
        result = _run_lark_cli(args, json_input=json_str)
        output = result.stdout
        stderr = result.stderr

        if result.returncode == 0:
            return {"ok": True, "table": table_name, "output": output}
        else:
            return {"ok": False, "error": output or stderr, "returncode": result.returncode}
    except Exception as e:
        return {"ok": False, "error": str(e)}
