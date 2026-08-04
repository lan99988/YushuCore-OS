"""Schedule calendar handler (Step2-4-C-10b).

迁移自 input_parser_old.handle_schedule_to_calendar（1287-1356），1:1 复刻业务逻辑。
编排型 handler：调用 daily_scheduler（获取任务/基线/生成排程）+ calendar_sync（同步到飞书日历）。
跨引擎依赖：每日排程引擎/daily_scheduler.py + 每日排程引擎/calendar_sync.py。

注意：
- 签名适配 dispatch 约定（raw_text 保留但业务不消费输入内容）。
- 保留延迟导入（try/except ImportError），因 daily_scheduler 和 calendar_sync 在独立引擎包中。
- 不修改 calendar_sync 的 CALENDAR_LOG_DIR（known issue Phase 5 治理）。
"""

import os
import sys
from datetime import datetime


def _ensure_schedule_engine_path():
    """轻量 sys.path 保护：确保每日排程引擎目录可导入。

    仅在 lazy import 时被调用，不预先注册兄弟引擎目录。
    与 input_parser_old._ensure_engine_paths() 逻辑一致但范围最小。
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    _engine_root = os.path.dirname(os.path.dirname(_here))  # 02_执行引擎（Engine）
    _schedule_engine = os.path.join(_engine_root, "每日排程引擎")
    if os.path.isdir(_schedule_engine) and _schedule_engine not in sys.path:
        sys.path.insert(0, _schedule_engine)


def handle_schedule_calendar(raw_text="", dry_run=False):
    """处理 #排程到日历 / #日历 指令：读取今日排程并同步到飞书日历

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定。
    raw_text 保留形参但不被消费（旧 handle_schedule_to_calendar 也无 text 参数）。

    用法：
        #排程到日历           → 同步今日排程到日历
        #排程到日历 --dry-run → 测试模式
    """
    try:
        _ensure_schedule_engine_path()
        from daily_scheduler import get_today_tasks, get_subject_baselines, generate_schedule
        from calendar_sync import sync_schedule_to_calendar

        target_date = datetime.now().strftime("%Y/%m/%d")

        # 1. 读取今日任务
        tasks = get_today_tasks(target_date)
        if not tasks:
            return {"ok": True, "type": "calendar", "message": "🎉 今天没有待办任务，无需同步到日历"}

        # 2. 读取科目基线
        baselines = get_subject_baselines()

        # 3. 生成排程
        schedule = generate_schedule(tasks, baselines, target_date, dry_run)

        if not schedule.get("timeline"):
            return {"ok": True, "type": "calendar", "message": "今日排程没有可写入日历的时段"}

        # 4. 同步到日历
        if dry_run:
            cal_result = sync_schedule_to_calendar(schedule, target_date, dry_run=True)
            return {
                "ok": True,
                "type": "calendar",
                "dry_run": True,
                "message": f"[TEST] 将创建 {len(schedule['timeline'])} 个日历事件、检测 {len(cal_result.get('conflicts', []))} 个冲突\n"
                           f"  待同步时段：{', '.join(s['slot'] for s in schedule['timeline'])}",
                "details": {
                    "slots": len(schedule['timeline']),
                    "tasks": len(tasks),
                    "conflicts": cal_result.get("conflicts", []),
                }
            }

        cal_result = sync_schedule_to_calendar(schedule, target_date)

        msg_parts = []
        if cal_result.get("created", 0) > 0:
            msg_parts.append(f"✅ 已同步 {cal_result['created']} 个时段到飞书日历")
        if cal_result.get("conflicts"):
            msg_parts.append(f"⚠️ 检测到 {len(cal_result['conflicts'])} 个冲突")
            for ci in cal_result["conflicts"]:
                conflict_details = f"  · {ci['slot']}（{ci['time']}）"
                for ce in ci["conflicting_events"][:2]:
                    conflict_details += f"\n    与「{ce.get('summary', '?')}」冲突"
                msg_parts.append(conflict_details)
            msg_parts.append("💡 如需调整，请告知我如何处理冲突（并行/重新安排）")

        if not msg_parts:
            msg_parts.append("今日排程同步完成，无异常")

        return {
            "ok": True,
            "type": "calendar",
            "message": "\n".join(msg_parts),
            "details": cal_result,
        }
    except ImportError as e:
        return {"ok": False, "type": "calendar", "error": f"日历同步模块未安装：{e}"}
    except Exception as e:
        return {"ok": False, "type": "calendar", "error": f"日历同步异常：{e}"}
