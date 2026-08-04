"""Habit checkin handler (Step2-4-C-9a).

迁移自 input_parser_old.handle_habit_checkin（1827-1961），1:1 复刻业务逻辑。
依赖：config.BASE_TOKEN + lark_bridge._run_lark_cli（飞书读写）+ json（标准库）。
HABITS_TABLE_ID 本地声明。
"""

import json

from ..config import BASE_TOKEN
from ..lark_bridge import _run_lark_cli

HABITS_TABLE_ID = "tblSRdG4P3XE75Ll"  # 习惯追踪表


def handle_habit_checkin(raw_text, dry_run=False):
    """处理 #习惯打卡 指令。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``。
    """
    content = raw_text.replace("#习惯打卡", "").strip()

    # 不带参数 → 显示待打卡列表
    if not content:
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
                return {"ok": True, "type": "habit_list", "message": "暂无习惯数据"}

            resp = json.loads(result.stdout)
            d = resp.get("data", {})
            field_names = d.get("fields", [])
            data_array = d.get("data", [])

            active = []
            for row in data_array:
                fields = dict(zip(field_names, row))
                def _get(fn, default=None):
                    v = fields.get(fn, default)
                    return v[0] if isinstance(v, list) and v else (v or default)
                if _get("状态") == "进行中":
                    active.append({
                        "name": _get("习惯名称", ""),
                        "streak": int(_get("当前连续天数", 0) or 0),
                        "identity": _get("身份声明", ""),
                    })

            if not active:
                return {"ok": True, "type": "habit_list", "message": "📋 没有进行中的习惯。用 `#习惯 每天XXX` 创建一个！"}

            msg = ["📋 【今日待打卡习惯】"]
            for h in active:
                fire = "🔥" * min(h["streak"] // 7, 3)
                tag = f"（{h['identity']}）" if h["identity"] else ""
                msg.append(f"  · 🔲 {h['name']}{tag} - 已连续{h['streak']}天{fire}")
            msg.append(f"\n💡 打卡：`#习惯打卡 {active[0]['name']}`")
            return {"ok": True, "type": "habit_list", "message": "\n".join(msg)}
        except Exception as e:
            return {"ok": True, "type": "habit_list", "message": f"查询失败：{e}"}

    # 有参数 → 打卡指定习惯
    habit_name = content
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
        record_ids = d.get("record_id_list", [])

        target = None
        target_id = ""
        for idx, row in enumerate(data_array):
            fields = dict(zip(field_names, row))
            def _get(fn, default=None):
                v = fields.get(fn, default)
                return v[0] if isinstance(v, list) and v else (v or default)
            if habit_name in _get("习惯名称", ""):
                target = fields
                target_id = record_ids[idx] if idx < len(record_ids) else ""
                break

        if not target:
            return {"ok": False, "type": "habit_error", "error": f"未找到习惯「{habit_name}」"}

        def _get(fn, default=None):
            v = target.get(fn, default)
            return v[0] if isinstance(v, list) and v else (v or default)

        name = _get("习惯名称", "")
        streak = int(_get("当前连续天数", 0) or 0)
        best = int(_get("历史最佳", 0) or 0)
        total = int(_get("总打卡次数", 0) or 0)
        identity = _get("身份声明", "")

        if dry_run:
            return {"ok": True, "dry_run": True, "type": "habit_checkin",
                    "message": f"[TEST] 打卡「{name}」：连续{streak+1}天"}

        new_streak = streak + 1
        new_best = max(best, new_streak)
        new_total = total + 1

        update_result = _run_lark_cli([
            "base", "+record-update",
            "--base-token", BASE_TOKEN,
            "--table-id", HABITS_TABLE_ID,
            "--record-id", target_id,
            "--json", "@_record_json",
            "--as", "user",
        ], json_input=json.dumps({
            "当前连续天数": new_streak,
            "历史最佳": new_best,
            "总打卡次数": new_total,
        }, ensure_ascii=False))

        msg = [f"✅ 已打卡「{name}」"]
        msg.append(f"  📊 已连续 {new_streak} 天（历史最佳：{new_best}天）| 总计{new_total}次")

        if new_streak == 7:
            msg.append("  🎉 连续7天——习惯开始形成了！")
        elif new_streak == 21:
            msg.append("  🏆 连续21天！习惯在自动化的路上")
        elif new_streak == 66:
            msg.append("  🏆 连续66天！习惯已经完全自动化了")
        elif new_streak > 0 and new_streak % 30 == 0:
            msg.append(f"  🎉 连续{new_streak}天里程碑！")

        if streak == 0:
            msg.append("  💪 走出了潜能蓄积区的第一步！")
        if identity:
            msg.append(f"  身份：{identity}")

        return {"ok": True, "type": "habit_checkin", "message": "\n".join(msg)}
    except Exception as e:
        return {"ok": False, "type": "habit_error", "error": str(e)}
