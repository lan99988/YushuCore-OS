"""
校验层

去重检查等纯校验逻辑。

注：deduplicate_check 本属 validators 职责，但因 feishu_write（Step2-2）
需在导入时引用，故提前落入本模块；Step2-3 不再重复迁移。
"""

import json

from .config import BASE_TOKEN, TABLES
from .lark_bridge import _run_lark_cli


def deduplicate_check(table_name, title, target_date, dry_run=False):
    """去重检查：检查执行库中是否已有同日期的同名任务

    Args:
        table_name: 表名
        title: 任务标题
        target_date: 目标日期 (yyyy/MM/dd)

    Returns:
        True 表示存在重复，应该跳过；False 表示无重复，可以继续
    """
    if table_name != "执行库" or not target_date:
        return False

    if dry_run:
        return False

    # 读取执行库所有记录
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES[table_name],
        "--as", "user",
        "--limit", "200",
        "--format", "json",
    ])

    if result.returncode != 0:
        return False

    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        for row in data_array:
            fields = dict(zip(field_names, row))
            # 检查标题模糊匹配（±2字符误差容忍）
            if abs(len(fields.get("标题", "")) - len(title)) <= 2:
                if title in fields.get("标题", "") or fields.get("标题", "") in title:
                    # 检查截止日期匹配
                    dl = fields.get("截止日期", "")
                    if dl and str(dl)[:10].replace("-", "/") == str(target_date)[:10].replace("-", "/"):
                        print(f"[WARN] [去重] 检测到重复任务：'{title}'（截止日期 {target_date} 已在执行库中）")
                        return True
    except (json.JSONDecodeError, KeyError):
        pass

    return False
