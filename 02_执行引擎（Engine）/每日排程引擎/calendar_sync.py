#!/usr/bin/env python3
"""
飞书日历同步模块
================
将每日排程结果同步到飞书日历，支持：
  - 学习时段创建区块日历事件
  - 冲突检测（+freebusy）
  - 自动顺延（+suggestion）
  - 手动触发（#排程到日历）

用法：
    python calendar_sync.py                          # 自动同步今日排程
    python calendar_sync.py --date 2026/07/02         # 指定日期
    python calendar_sync.py --dry-run                 # 测试模式（不写入）
    python calendar_sync.py --clear                   # 清空今日同步事件
"""

import json
import subprocess
import os
import sys
import re
import uuid
from datetime import datetime, date, timedelta

# ============ 配置 ============
LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\.bin\lark-cli.cmd"
USER_OPEN_ID = "ou_adf2c637b6ddd79c0af429ad5da3a746"
PRIMARY_CALENDAR_ID = "feishu.cn_ITW1W18F8oLcPqgahpLA6f@group.calendar.feishu.cn"
TIMEZONE = "+08:00"

# 运行时日志路径
CALENDAR_LOG_DIR = os.path.join(os.path.dirname(__file__), "runtime")
CALENDAR_LOG_FILE = os.path.join(CALENDAR_LOG_DIR, "_calendar_log.json")

# 精力等级 → 日历标题图标
ENERGY_ICON = {
    "高": "🔴",
    "中": "🟡",
    "低": "🟢",
}

# 任务类型 → 日历标题图标（独立任务用）
TASK_ICON = {
    "social": "🤝",
    "core": "🎯",
    "task": "📋",
}

# 独立任务识别（从schedule中提取非学习类事件）
SOCIAL_KEYWORDS = ["生日", "联系", "见面", "社交", "微信", "电话"]


# ============ 工具函数 ============

def _run_lark(args_list, json_input=None):
    """运行 lark-cli 命令"""
    tmp_path = None
    if json_input:
        tmp_name = f"_lark_tmp_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json_input)
        new_args = []
        i = 0
        while i < len(args_list):
            if args_list[i] == "--json" and i + 1 < len(args_list):
                new_args.append("--json")
                new_args.append(f"@{tmp_name}")
                i += 2
            else:
                new_args.append(args_list[i])
                i += 1
        args_list = new_args

    def try_decode(data):
        if data is None:
            return ""
        for enc in ["utf-8", "gbk", "gb2312", "cp936"]:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")

    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # 方法1: 直接运行 .cmd 文件（Python 在 Windows 上会自动通过 cmd.exe 执行）
    cli_cmd = LARK_CLI.replace("lark-cli", "lark-cli.cmd")
    if not cli_cmd.endswith(".cmd"):
        alt_path = LARK_CLI + ".cmd"
        if os.path.exists(alt_path):
            cli_cmd = alt_path
        else:
            ws_cmd = os.path.join(
                os.path.dirname(LARK_CLI), "..", "workspace",
                "node_modules", ".bin", "lark-cli.cmd"
            )
            if os.path.exists(ws_cmd):
                cli_cmd = ws_cmd
    try:
        full_args = [cli_cmd] + args_list
        result = subprocess.run(
            full_args,
            capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        result.stdout = try_decode(result.stdout)
        result.stderr = try_decode(result.stderr)
        _cleanup()
        return result
    except (FileNotFoundError, OSError):
        pass

    # 方法2: 通过 bash 包装器（降级方案）
    cli_path = LARK_CLI.replace("\\", "/")
    cmd_parts = [f'"{cli_path}"'] + [f'"{a}"' for a in args_list]
    cmd_str = " ".join(cmd_parts)

    for bash_cmd in [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        "bash",
    ]:
        try:
            result = subprocess.run(
                [bash_cmd, "-c", cmd_str],
                capture_output=True, timeout=60
            )
            result.stdout = try_decode(result.stdout)
            result.stderr = try_decode(result.stderr)
            _cleanup()
            return result
        except (FileNotFoundError, OSError):
            continue

    _cleanup()
    raise FileNotFoundError("lark-cli not found")


def _lark_json(args_list):
    """运行 lark-cli 并返回解析后的 JSON"""
    result = _run_lark(args_list)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr or result.stdout}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": result.stdout}


def _to_iso(datestr, timestr):
    """将日期+时间转为 ISO 8601 格式
    
    Args:
        datestr: "2026/07/01" 或 "2026-07-01"
        timestr: "09:00"
    Returns:
        "2026-07-01T09:00:00+08:00"
    """
    d = datestr.replace("/", "-")
    return f"{d}T{timestr}:00{TIMEZONE}"


def _parse_date_str(s):
    """解析日期为 yyyy-MM-dd 格式"""
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _today_str():
    return date.today().strftime("%Y-%m-%d")


# ============ 日历日志 ============

def _load_calendar_log(target_date=None):
    """读取日历同步日志"""
    if target_date is None:
        target_date = _today_str()
    if os.path.exists(CALENDAR_LOG_FILE):
        try:
            with open(CALENDAR_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == target_date:
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": target_date, "events": [], "conflicts": [], "cleared": False}


def _save_calendar_log(data):
    """保存日历同步日志"""
    os.makedirs(CALENDAR_LOG_DIR, exist_ok=True)
    with open(CALENDAR_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _log_event(event_data):
    """追加一条事件记录到日志"""
    log = _load_calendar_log()
    log.setdefault("events", [])
    log["events"].append(event_data)
    _save_calendar_log(log)


def _log_conflict(conflict_data):
    """追加一条冲突记录到日志"""
    log = _load_calendar_log()
    log.setdefault("conflicts", [])
    log["conflicts"].append(conflict_data)
    _save_calendar_log(log)


# ============ 核心 API ============

def check_date_freebusy(target_date=None, *, strict=False):
    """查询指定日期的忙闲状态
    
    Args:
        target_date: "2026-07-01" 或 "2026/07/01"
    
    Returns:
        [{"start": "2026-07-01T09:00:00+08:00", "end": "...", "summary": "..."}, ...]
    """
    if target_date is None:
        target_date = _today_str()
    else:
        target_date = _parse_date_str(target_date)
    
    start_iso = f"{target_date}T00:00:00{TIMEZONE}"
    end_iso = f"{target_date}T23:59:59{TIMEZONE}"
    
    result = _lark_json([
        "calendar", "+freebusy",
        "--start", start_iso,
        "--end", end_iso,
        "--as", "user",
    ])
    
    if not result.get("ok"):
        if strict:
            raise RuntimeError("calendar_freebusy_query_failed")
        print(f"[WARN] 查询忙闲失败: {result.get('error')}")
        return []
    
    # +freebusy 返回结构可能为：
    #   {data: {busy: [...]}}  — 单个日历
    #   {data: [{busy: [...]}, ...]}  — 多个日历（列表）
    #   {data: null}  — 全空闲
    data = result.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        busy_list = []
        for item in data:
            busy_list.extend(item.get("busy", []))
    else:
        busy_list = data.get("busy", [])
    
    events = []
    for item in busy_list:
        events.append({
            "start": item.get("start", {}).get("datetime", ""),
            "end": item.get("end", {}).get("datetime", ""),
            "summary": item.get("summary", "[未知事件]"),
            "calendar_id": item.get("calendar_id", ""),
        })
    
    return events


def check_slot_freebusy(slot_start_iso, slot_end_iso, *, strict=False):
    """查询某个时间段是否空闲
    
    Args:
        slot_start_iso: "2026-07-01T09:00:00+08:00"
        slot_end_iso: "2026-07-01T10:30:00+08:00"
    
    Returns:
        ([conflict_events], is_free)
    """
    result = _lark_json([
        "calendar", "+freebusy",
        "--start", slot_start_iso,
        "--end", slot_end_iso,
        "--as", "user",
    ])
    
    if not result.get("ok"):
        if strict:
            raise RuntimeError("calendar_freebusy_query_failed")
        return ([], True)  # 查询失败，默认空闲不阻塞
    
    data = result.get("data")
    if data is None:
        return ([], True)
    if isinstance(data, list):
        busy_list = []
        for item in data:
            busy_list.extend(item.get("busy", []))
    else:
        busy_list = data.get("busy", [])
    
    conflicts = []
    for item in busy_list:
        conflicts.append({
            "start": item.get("start", {}).get("datetime", ""),
            "end": item.get("end", {}).get("datetime", ""),
            "summary": item.get("summary", "[未知事件]"),
        })
    
    return (conflicts, len(conflicts) == 0)


def create_calendar_event(summary, start_iso, end_iso, description="", dry_run=False):
    """创建单个日历事件
    
    Args:
        summary: 事件标题
        start_iso: 开始时间 ISO 8601
        end_iso: 结束时间 ISO 8601
        description: 事件描述
        dry_run: 测试模式
    
    Returns:
        {"ok": True, "event_id": "xxx"} 或 {"ok": False, "error": "..."}
    """
    if dry_run:
        print(f"[DRY-RUN] 创建日历事件：{summary}")
        print(f"  时间：{start_iso} → {end_iso}")
        if description:
            print(f"  描述：{description[:100]}...")
        return {"ok": True, "dry_run": True, "summary": summary}
    
    result = _run_lark([
        "calendar", "+create",
        "--summary", summary,
        "--start", start_iso,
        "--end", end_iso,
        "--as", "user",
    ])
    
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr or result.stdout}
    
    try:
        resp = json.loads(result.stdout)
        data = resp.get("data", {})
        event_id = data.get("event_id", data.get("id", ""))
        return {
            "ok": True,
            "event_id": event_id,
            "calendar_id": PRIMARY_CALENDAR_ID,
            "summary": summary,
        }
    except json.JSONDecodeError:
        return {"ok": True, "calendar_id": PRIMARY_CALENDAR_ID, "summary": summary, "raw": result.stdout}


def find_next_available_slot(duration_minutes, after_iso, *, strict=False):
    """找下一个可用的空闲时段
    
    Args:
        duration_minutes: 需要的时长（分钟）
        after_iso: 搜索起始时间 ISO 8601
    
    Returns:
        {"start": "2026-07-01T...", "end": "..."} 或 None
    """
    # 搜索到当天结束
    end_iso = after_iso[:10] + "T23:59:59" + TIMEZONE
    
    result = _lark_json([
        "calendar", "+suggestion",
        "--duration-minutes", str(duration_minutes),
        "--start", after_iso,
        "--end", end_iso,
        "--as", "user",
    ])
    
    if not result.get("ok"):
        if strict:
            raise RuntimeError("calendar_suggestion_query_failed")
        return None
    
    data = result.get("data", {})
    suggestions = data.get("suggestions", [])
    
    if not suggestions:
        return None
    
    # 取第一个建议
    slot = suggestions[0]
    return {
        "start": slot.get("start", {}).get("datetime", ""),
        "end": slot.get("end", {}).get("datetime", ""),
    }


def clear_today_schedule_events(dry_run=False):
    """清空今日已同步的排程事件（用于重新排程时）
    
    Returns:
        {"cleared": count, "events": [...]}
    """
    log = _load_calendar_log()
    events = log.get("events", [])
    
    if not events:
        return {"cleared": 0, "events": []}
    
    cleared = []
    for ev in events:
        event_id = ev.get("event_id")
        if not event_id:
            continue
        if dry_run:
            print(f"[DRY-RUN] 删除日历事件：{ev.get('summary', '')} ({event_id})")
            cleared.append(event_id)
            continue
        
        result = _run_lark([
            "calendar", "events", "delete",
            "--event-id", event_id,
            "--calendar-id", ev.get("calendar_id", PRIMARY_CALENDAR_ID),
            "--as", "user",
        ])
        if result.returncode == 0:
            cleared.append(event_id)
        else:
            print(f"[WARN] 删除事件失败：{ev.get('summary', '')} - {result.stderr}")
    
    # 更新日志
    log["events"] = []
    log["cleared"] = True
    _save_calendar_log(log)
    
    return {"cleared": len(cleared), "events": cleared}


def _build_slot_event_summary(slot):
    """构建学习时段事件的标题
    
    Args:
        slot: timeline 中的一个时段 dict
    Returns:
        "🔴 高效段① · 数学"
    """
    icon = ENERGY_ICON.get(slot["energy"], "📋")
    
    # 提取此时段内任务的科目类别
    categories = set()
    for t in slot.get("tasks", []):
        cat = t.get("category", "")
        if cat:
            categories.add(cat)
    
    cat_str = " · ".join(sorted(categories)) if categories else "学习"
    
    return f"{icon} {slot['slot']} · {cat_str}"


def _build_slot_event_description(slot):
    """构建学习时段事件的详细描述"""
    lines = []
    lines.append("📋 今日任务：")
    for t in slot.get("tasks", []):
        mark = " ⭐ " if t.get("is_tough") else " · "
        lines.append(f"  {mark}{t['title']}（{t['est_time']}分钟）")
    
    # 硬骨头特别标注
    tough = [t for t in slot.get("tasks", []) if t.get("is_tough")]
    if tough:
        lines.append("")
        lines.append("⭐ 硬骨头：")
        for t in tough:
            lines.append(f"  · {t['title']}")
    
    return "\n".join(lines)


def _build_independent_event(task, task_type="task"):
    """构建独立任务的日历事件信息
    
    Args:
        task: 任务 dict
        task_type: "task" | "social"
    
    Returns:
        {"summary": "...", "description": "...", "duration_minutes": N}
    """
    icon = TASK_ICON.get(task_type, "📋")
    summary = f"{icon} {task['title']}"
    
    desc_lines = []
    desc_lines.append(f"优先级：{task.get('priority', 'P3')}")
    if task.get("est_time"):
        desc_lines.append(f"预估耗时：{task['est_time']}分钟")
    if task.get("deadline"):
        desc_lines.append(f"截止日期：{task['deadline']}")
    
    return {
        "summary": summary,
        "description": "\n".join(desc_lines),
        "duration_minutes": task.get("est_time", 30),
    }


# ============ 主同步逻辑 ============

def sync_schedule_to_calendar(schedule, target_date=None, dry_run=False):
    """将排程结果同步到飞书日历
    
    流程：
    1. 清空今日已同步的排程事件（避免重复）
    2. 遍历每个学习时段，检测冲突
    3. 无冲突 → 直接创建日历事件
    4. 有冲突 → 标记冲突，返回冲突清单
    5. 记录同步日志
    
    Args:
        schedule: daily_scheduler.generate_schedule() 的输出
        target_date: 目标日期 (yyyy/MM/dd 或 yyyy-MM-dd)
        dry_run: 测试模式
    
    Returns:
        {
            "ok": True/False,
            "created": N,
            "events": [{"event_id": "...", "summary": "...", "start": "...", "end": "..."}],
            "conflicts": [
                {
                    "slot": "高效段①",
                    "time": "09:00-10:30",
                    "conflicting_events": [{"summary": "...", "start": "...", "end": "..."}]
                },
                ...
            ],
            "summary": "文本摘要"
        }
    """
    if target_date is None:
        target_date = _today_str()
    else:
        target_date = _parse_date_str(target_date)
    
    timeline = schedule.get("timeline", [])
    if not timeline:
        return {"ok": True, "created": 0, "events": [], "conflicts": [], "summary": "今日无可排入的时段"}
    
    result_events = []
    result_conflicts = []
    
    # 第一步：清理今日已有排程事件（避免重复写入）
    if not dry_run:
        clear_today_schedule_events(dry_run=False)
    
    # 第二步：遍历每个时段
    for slot in timeline:
        slot_name = slot["slot"]
        time_range = slot["time"]  # "09:00-10:30"
        
        # 解析起止时间
        if "-" not in time_range:
            continue
        start_time, end_time = time_range.split("-", 1)
        
        start_iso = _to_iso(target_date, start_time.strip())
        end_iso = _to_iso(target_date, end_time.strip())
        
        # 检查冲突
        conflicts, is_free = check_slot_freebusy(start_iso, end_iso)
        
        if is_free:
            # 无冲突 → 直接创建
            summary = _build_slot_event_summary(slot)
            description = _build_slot_event_description(slot)
            
            result = create_calendar_event(summary, start_iso, end_iso, description, dry_run)
            
            if result.get("ok"):
                event_info = {
                    "event_id": result.get("event_id", ""),
                    "calendar_id": result.get("calendar_id", ""),
                    "summary": summary,
                    "start": start_iso,
                    "end": end_iso,
                    "slot": slot_name,
                    "status": "created",
                }
                result_events.append(event_info)
                
                # 记录日志
                if not dry_run:
                    _log_event(event_info)
                
                print(f"  ✅ 创建事件：{summary}（{start_time}～{end_time}）")
            else:
                print(f"  ❌ 创建失败：{summary} - {result.get('error')}")
        else:
            # 有冲突 → 标记
            conflict_info = {
                "slot": slot_name,
                "time": f"{start_time}-{end_time}",
                "conflicting_events": conflicts,
            }
            result_conflicts.append(conflict_info)
            
            if not dry_run:
                _log_conflict(conflict_info)
            
            print(f"  ⚠️ 冲突：{slot_name}（{start_time}～{end_time}）")
            for ce in conflicts:
                ce_start = ce.get("start", "")[11:16] if len(ce.get("start", "")) > 16 else ce.get("start", "")
                ce_end = ce.get("end", "")[11:16] if len(ce.get("end", "")) > 16 else ce.get("end", "")
                print(f"     冲突事件：{ce.get('summary', '?')}（{ce_start}～{ce_end}）")
    
    # 构建摘要
    summary_lines = []
    if result_events:
        summary_lines.append(f"✅ 已同步 {len(result_events)} 个时段到日历")
    if result_conflicts:
        for ci in result_conflicts:
            title = f"  · {ci['slot']}（{ci['time']}）"
            for ce in ci["conflicting_events"][:2]:
                title += f"\n    与「{ce.get('summary', '?')}」冲突"
            summary_lines.append(f"⚠️ {title}")
        summary_lines.append("可通过 #排程到日历 重新安排冲突时段")
    
    return {
        "ok": True,
        "created": len(result_events),
        "events": result_events,
        "conflicts": result_conflicts,
        "summary": "\n".join(summary_lines),
    }


def reschedule_conflict(slot_name, duration_minutes, after_iso, dry_run=False):
    """将冲突的时段重新安排到下一个空闲时段
    
    Args:
        slot_name: 时段名称
        duration_minutes: 需要的时长
        after_iso: 搜索起始时间
        dry_run: 测试模式
    
    Returns:
        {"ok": True, "new_start": "...", "new_end": "..."} 或 {"ok": False}
    """
    suggestion = find_next_available_slot(duration_minutes, after_iso)
    if not suggestion:
        return {"ok": False, "error": "今日无可用空闲时段"}
    
    new_start = suggestion["start"]
    new_end = suggestion["end"]
    
    # 创建新事件
    new_summary = f"🔄 {slot_name}（已调整）"
    result = create_calendar_event(new_summary, new_start, new_end, "已从原时段调整至此", dry_run)
    
    if result.get("ok"):
        # 清除旧的冲突标记
        log = _load_calendar_log()
        log["conflicts"] = [c for c in log.get("conflicts", []) if c.get("slot") != slot_name]
        _save_calendar_log(log)
        
        return {
            "ok": True,
            "new_start": new_start,
            "new_end": new_end,
            "summary": new_summary,
        }
    else:
        return {"ok": False, "error": result.get("error")}


# ============ 主入口 ============

def main():
    dry_run = "--dry-run" in sys.argv
    clear_mode = "--clear" in sys.argv
    target_date = None
    
    for arg in sys.argv[1:]:
        if arg.startswith("--date="):
            target_date = arg.split("=", 1)[1]
    
    if clear_mode:
        result = clear_today_schedule_events(dry_run)
        print(f"已清理 {result['cleared']} 个日历事件")
        return
    
    # 测试模式：直接读取当前排程（需要从Base读取）
    if not target_date:
        target_date = _today_str()
    
    from daily_scheduler import get_today_tasks, get_subject_baselines, generate_schedule
    
    tasks = get_today_tasks(target_date)
    if not tasks:
        print("🎉 今天没有待办任务")
        return
    
    baselines = get_subject_baselines()
    schedule = generate_schedule(tasks, baselines, target_date, dry_run)
    
    # 同步到日历
    result = sync_schedule_to_calendar(schedule, target_date, dry_run)
    
    print("\n" + "=" * 50)
    if result["conflicts"]:
        print("⚠️ 存在日历冲突：")
        for ci in result["conflicts"]:
            print(f"  · {ci['slot']}（{ci['time']}）")
            for ce in ci["conflicting_events"]:
                print(f"    冲突：{ce.get('summary', '?')}")
    if result["created"] > 0:
        print(f"✅ 成功创建 {result['created']} 个日历事件")
    print("=" * 50)


if __name__ == "__main__":
    main()
