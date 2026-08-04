"""Habit progress handler (Step2-4-C-9c).

迁移自 input_parser_old.handle_habit_progress（1964-2041），1:1 复刻业务逻辑。
查询型 handler：飞书读习惯数据 → 本地格式统计展示，无写入、无 runtime。
依赖：config.BASE_TOKEN + lark_bridge._run_lark_cli + json（标准库）。
HABITS_TABLE_ID 本地声明，与 habit/habit_checkin 共享同一常量值。
"""

import json

from ..config import BASE_TOKEN
from ..lark_bridge import _run_lark_cli

HABITS_TABLE_ID = "tblSRdG4P3XE75Ll"  # 习惯追踪表


def handle_habit_progress(text, dry_run=False):
    """处理 #习惯进度 指令：查看习惯详情

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定。

    用法：
        #习惯进度 背单词
    """
    content = text.replace("#习惯进度", "").strip()
    if not content:
        return {"ok": True, "type": "habit_error", "message": "请指定习惯名：`#习惯进度 背单词`"}

    try:
        result = _run_lark_cli([
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", HABITS_TABLE_ID,
            "--as", "user",
            "--limit", "50",
            "--format", "json",
        ])
        if result.returncode != 0:
            return {"ok": False, "type": "habit_error", "error": "读取习惯表失败"}

        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        target = None
        for row in data_array:
            fields = dict(zip(field_names, row))

            def _get(fn, default=None):
                v = fields.get(fn, default)
                return v[0] if isinstance(v, list) and v else (v or default)

            if content in _get("习惯名称", ""):
                target = fields
                break

        if not target:
            return {"ok": False, "type": "habit_error", "error": f"未找到习惯「{content}」"}

        def _get(fn, default=None):
            v = target.get(fn, default)
            return v[0] if isinstance(v, list) and v else (v or default)

        msg = [f"🏋️ 【习惯详情：{_get('习惯名称', '')}】"]

        if v := _get("身份声明", ""):
            msg.append(f"  身份：{v}")
        if v := _get("执行意图", ""):
            msg.append(f"  执行意图：{v}")
        if v := _get("习惯叠加", ""):
            msg.append(f"  习惯叠加：在{v}之后")
        if v := _get("提示位置", ""):
            msg.append(f"  环境提示：{v}")

        streak = int(_get("当前连续天数", 0) or 0)
        best = int(_get("历史最佳", 0) or 0)
        total = int(_get("总打卡次数", 0) or 0)
        freq = _get("频率", "每天")
        msg.append(f"  频率：{freq} | 连续{streak}天 | 最佳{best}天 | 总计{total}次")

        suggestions = []
        if not _get("身份声明", ""):
            suggestions.append("  缺乏身份声明 → 用【我是：XXX】来定义新身份")
        if not _get("执行意图", "") and not _get("习惯叠加", ""):
            suggestions.append("  没有执行意图 → 明确「何时何地做」会提高执行率")
        if not _get("提示位置", ""):
            suggestions.append("  没有环境提示 → 设计一个明显的视觉提示")
        if streak >= 7:
            suggestions.append("  ✅ 已连续7天+，习惯开始自动化了！")
        if streak == 0 and total == 0:
            suggestions.append("  💡 先用两分钟规则：只做2分钟版本开始")

        if suggestions:
            msg.append("")
            msg.append("💡 建议：")
            for s in suggestions:
                msg.append(f"  {s}")

        return {"ok": True, "type": "habit_progress", "message": "\n".join(msg)}
    except Exception as e:
        return {"ok": False, "type": "habit_error", "error": str(e)}
