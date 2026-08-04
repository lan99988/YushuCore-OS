"""Deep record handler (Step2-4-C-8b).

迁移自 input_parser_old.handle_deep_record（1419-1523），1:1 复刻业务逻辑。
依赖：config.BASE_TOKEN + lark_bridge._run_lark_cli（飞书写）+ 标准库（re/os/json/datetime）。
DEEP_WORK_TABLE_ID 本地声明，与 review.py 各自持有，不跨文件重构。
"""

import re
import json
from datetime import datetime

from ..config import BASE_TOKEN
from ..lark_bridge import _run_lark_cli

DEEP_WORK_TABLE_ID = "tblmAz37er4CEbL0"  # 深度工作追踪表


def handle_deep_record(raw_text, dry_run=False):
    """处理 #深度记录 指令：记录当天的深度工作表现。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``。
    """
    content = raw_text.replace("#深度记录", "").strip()

    record = {
        "日期": datetime.now().strftime("%Y/%m/%d"),
    }

    # 解析深度工作时长
    m = re.search(r'深度\s*(\d+\.?\d*)\s*h(?:ours?|r)?', content, re.IGNORECASE)
    if m:
        record["当日深度工作时长(min)"] = int(float(m.group(1)) * 60)
    m = re.search(r'深度\s*(\d+\.?\d*)\s*小时', content)
    if m:
        record["当日深度工作时长(min)"] = int(float(m.group(1)) * 60)

    # 解析心流状态
    flow_map = {"无": "无", "低": "低", "中": "中", "高": "高", "巅峰": "巅峰"}
    for keyword, status in flow_map.items():
        if keyword in content:
            record["最高心流状态"] = status
            break

    # 解析干扰次数
    m = re.search(r'干扰\s*(\d+)\s*次', content)
    if m:
        record["干扰次数"] = int(m.group(1))

    # 解析浮浅占比
    m = re.search(r'浮浅\s*(\d+)%', content)
    if m:
        record["当日浮浅工作占比"] = int(m.group(1))

    # 解析备注
    m = re.search(r'备注[：:]\s*(.+?)$', content)
    if m:
        record["备注"] = m.group(1).strip()
    m = re.search(r'#(\S+)', content)
    if m and "备注" not in record:
        record["备注"] = m.group(1)

    # 🆕 解析恢复活动（ART）
    m = re.search(r'恢复活动[：:]\s*(.+?)(?:\s|$)', content)
    if m:
        record["恢复活动"] = m.group(1).strip()
    m = re.search(r'恢复[：:]\s*(.+?)(?:\s|$)', content)
    if m and "恢复活动" not in record:
        record["恢复活动"] = m.group(1).strip()

    # 🆕 解析第一勺完成状态
    if "第一勺完成" in content or "第一勺已完成" in content:
        record["第一勺完成"] = True
    elif "第一勺未完成" in content:
        record["第一勺完成"] = False

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "type": "deep_record",
            "message": f"[TEST] 深度工作记录：{json.dumps(record, ensure_ascii=False)}",
            "record": record,
        }

    # 写入深度工作追踪表（通过lark-cli）
    try:
        # 过滤空值
        fields = {k: v for k, v in record.items() if v is not None}
        json_str = json.dumps(fields, ensure_ascii=False)

        args = [
            "base", "+record-upsert",
            "--base-token", BASE_TOKEN,
            "--table-id", DEEP_WORK_TABLE_ID,
            "--json", "@_record_json",
            "--as", "user",
        ]
        result = _run_lark_cli(args, json_input=json_str)
        if result.returncode == 0:
            return {
                "ok": True,
                "type": "deep_record",
                "message": f"✅ 深度工作记录已保存：{record}",
                "record": record,
            }
        else:
            return {
                "ok": False,
                "type": "deep_record",
                "error": f"写入失败：{result.stderr or result.stdout}",
            }
    except Exception as e:
        return {
            "ok": True,  # 降级：记录到本地
            "type": "deep_record",
            "message": f"📝 深度记录已保存（本地）：{json.dumps(record, ensure_ascii=False)}",
            "record": record,
            "fallback": str(e),
        }
