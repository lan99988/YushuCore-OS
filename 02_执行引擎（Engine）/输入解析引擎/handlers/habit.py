"""Habit creation handler (Step2-4-C-9b).

迁移自 input_parser_old.handle_habit（1732-1824），1:1 复刻业务逻辑。
依赖：config.BASE_TOKEN + lark_bridge._run_lark_cli（飞书写入）+ json/re（标准库）。
HABITS_TABLE_ID 本地声明，与 habit_checkin 共享同一常量值。
"""

import json
import re

from ..config import BASE_TOKEN
from ..lark_bridge import _run_lark_cli

HABITS_TABLE_ID = "tblSRdG4P3XE75Ll"  # 习惯追踪表


def handle_habit(raw_text, dry_run=False):
    """处理 #习惯 指令：创建新习惯。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定。

    用法：
        #习惯 每天背20个单词 【我是：背词者】【在早饭后在书桌前】【提示：单词本放桌面】【频率：每天】
    """
    content = raw_text.replace("#习惯", "").strip()

    if not content:
        return {
            "ok": True, "type": "habit_help",
            "message": "🏋️ 【习惯追踪】\n"
                       "  · #习惯 每天背20单词 → 创建习惯\n"
                       "  · #习惯打卡 背单词 → 打卡\n"
                       "  · #习惯打卡 → 查看今日待打卡\n"
                       "  · #习惯进度 背单词 → 查看进度"
        }

    # 解析习惯名（去掉标记后剩余的纯文本）
    name = re.sub(r'【[^】]*】', '', content).strip()

    # 提取变量
    identity = ""
    m = re.search(r'【我是[：:]\s*(.+?)】', content)
    if m:
        identity = m.group(1).strip()

    location = ""
    m = re.search(r'【在[：:]\s*(.+?)】', content)
    if m:
        location = m.group(1).strip()

    stacking = ""
    m = re.search(r'【在(.+?)之后】', content)
    if m:
        stacking = m.group(1).strip()

    cue = ""
    m = re.search(r'【提示[：:]\s*(.+?)】', content)
    if m:
        cue = m.group(1).strip()

    frequency = "每天"
    m = re.search(r'【频率[：:]\s*(.+?)】', content)
    if m:
        raw_freq = m.group(1).strip()
        if raw_freq in ["每天", "每周2-3次", "每周1次", "自定义"]:
            frequency = raw_freq

    if not name:
        return {"ok": True, "type": "habit_error", "message": "⚠️ 请指定习惯名称，如：`#习惯 每天背单词`"}

    # 构造字段
    fields = {
        "习惯名称": name,
        "身份声明": identity,
        "执行意图": location,
        "习惯叠加": stacking,
        "提示位置": cue,
        "频率": frequency,
        "当前连续天数": 0,
        "历史最佳": 0,
        "总打卡次数": 0,
        "状态": "进行中",
    }
    fields = {k: v for k, v in fields.items() if v is not None and v != ""}

    if dry_run:
        return {"ok": True, "dry_run": True, "type": "habit_create", "payload": fields}

    try:
        json_str = json.dumps(fields, ensure_ascii=False)
        args = [
            "base", "+record-upsert",
            "--base-token", BASE_TOKEN,
            "--table-id", HABITS_TABLE_ID,
            "--json", "@_record_json",
            "--as", "user",
        ]
        result = _run_lark_cli(args, json_input=json_str)
        if result.returncode == 0:
            msg_parts = [f"✅ 习惯「{name}」已创建"]
            if identity:
                msg_parts.append(f"  身份宣言：{identity}")
            if location:
                msg_parts.append(f"  执行意图：{location}")
            if cue:
                msg_parts.append(f"  提示位置：{cue}")
            msg_parts.append(f"  💡 先用两分钟规则开始：只做2分钟版本")
            return {"ok": True, "type": "habit_create", "message": "\n".join(msg_parts)}
        return {"ok": False, "type": "habit_error", "error": f"写入失败：{result.stderr or result.stdout}"}
    except Exception as e:
        return {"ok": False, "type": "habit_error", "error": str(e)}
