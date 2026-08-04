#!/usr/bin/env python3
"""
每日排程生成器
==============
读取执行库今日待办，生成作战时间轴，创建飞书任务，推送飞书消息。
v2.0 新增：核心事件 + 社交提醒 + 财务概览 + 创作进展 + 知识统计

支持动态时长调整：
  - 精力差 → 乘以 0.8 系数
  - 精力好 → 乘以 1.2 系数
  - 可通过 #配置 今日可用时长 11小时 自定义
  - 可通过 #配置 精力系数 0.9 自定义

用法：
    python daily_scheduler.py                  # 正常模式
    python daily_scheduler.py --dry-run        # 测试模式
    python daily_scheduler.py --date 2026/07/01  # 指定日期
"""

import json
import subprocess
import os
import sys
import re
import uuid
from datetime import datetime, date, timedelta

# ============ 引擎跨目录导入引导 ============
# 重构后各引擎按子目录组织，`from calendar_sync import ...` / `from analytics_engine import ...`
# 等兄弟导入需将兄弟引擎目录加入 sys.path 才能解析。
def _ensure_engine_paths():
    import os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _engine_root = _os.path.dirname(_here)  # 02_执行引擎（Engine）
    _candidates = [
        _here,
        _os.path.join(_engine_root, "输入解析引擎"),
        _os.path.join(_engine_root, "数据分析引擎"),
        _os.path.join(_engine_root, "复盘分析引擎"),
        _os.path.join(_engine_root, "每日排程引擎"),
        _os.path.join(_os.path.dirname(_engine_root), "03_领域模块（Modules）", "比赛管理（Competition）", "程序"),
    ]
    for _p in _candidates:
        if _os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
_ensure_engine_paths()

# ============ 配置 ============
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
TABLES = {
    "执行库": "tblNQCB4pn6Rso4a",
    "灵感库": "tblx1ZaQGwXvoJhj",
    "Bug库": "tblPpPputYMACtQ5",
    "科目进度基线": "tblQnjCO03WjQ7GC",
    "财务流水表": "tblPFKBGubeIYsfm",
    "社交关系表": "tblt7uTkIcLhH7bs",
    "创作素材表": "tbl99pDAlTIDu7f5",
    "知识笔记表": "tblgtdx4h0EJjRrh",
    "深度工作追踪表": "tblmAz37er4CEbL0",
    "习惯追踪表": "tblSRdG4P3XE75Ll",  # 🆕 习惯追踪
}

# lark-cli 路径（优先用 .cmd 文件，可直接在 Windows 上运行）
LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\.bin\lark-cli.cmd"

# 用户飞书 open_id
USER_OPEN_ID = "ou_adf2c637b6ddd79c0af429ad5da3a746"

# 精力等级→时段映射
SLOT_MAP = {
    "高": ("09:00", "11:30", "黄金段"),
    "中": ("14:00", "17:00", "常规段"),
    "低": ("20:00", "22:00", "晚间段"),
}

# 优先级名称→权重
PRIORITY_WEIGHT = {
    "P0-重要紧急": 100,
    "P1-重要不紧急": 80,
    "P2-紧急不重要": 60,
    "P3-不重要不紧急": 40,
}

# ===== 新版时段体系 =====
# 高效学习：全身心投入，之后需要休息恢复
# 可支配完整时间：专注但不极致，零散时间的反义词
# 零散时间：碎片化，适合低精力/复习型任务
SLOT_LAYOUT = [
    # (时段名称, 开始, 结束, 精力等级, 模式, 备注)
    ("高效段①", "09:00", "10:30", "高", "🔴深度", "深度工作·黄金时段"),
    ("休息",    "10:30", "10:45", None,   None,    "恢复精力"),
    ("高效段②", "10:45", "12:15", "高", "🔴深度", "深度工作·黄金时段"),
    ("午休",    "12:15", "14:00", None,   None,    "午餐+休息"),
    ("完整段①", "14:00", "17:00", "中", "🟡深度/浮浅", "深度工作(可选)"),
    ("休息",    "17:00", "17:15", None,   None,    "短暂放松"),
    ("完整段②", "17:15", "18:45", "中", "🟢浮浅优先", "浮浅工作优先"),
    ("晚餐",    "18:45", "20:00", None,   None,    "晚餐"),
    ("零散段",  "20:00", "22:00", "低", "🟢浮浅", "浮浅工作·低强度"),
]

# 高效总时长：3h
HIGH_FOCUS_TOTAL = 180  # 分钟
# 完整时间：高效以外的整块时间 = 3h + 1.5h = 4.5h
BLOCK_TOTAL = 270  # 分钟
# 零散时间：2h
SCATTERED_TOTAL = 120  # 分钟

DEFAULT_DAILY_HOURS = 10.0
LOW_ENERGY_HOURS = 8.0
HIGH_ENERGY_HOURS = 12.0
ENERGY_STATUS_FILE = os.path.join(os.path.dirname(__file__), "runtime", "_energy_status.json")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "runtime", "_schedule_config.json")
BODY_OS_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "04_数据中心（Data）", "系统配置（Config）", "body_os_config.json")


def load_config():
    """读取自定义配置"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return config


def save_config(key, value):
    """保存配置项"""
    config = load_config()
    config[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config


def _today_iso(today=None):
    if today is None:
        return date.today().isoformat()
    text = str(today).strip()
    if "/" in text:
        try:
            return datetime.strptime(text[:10], "%Y/%m/%d").date().isoformat()
        except ValueError:
            return text.replace("/", "-")
    return text[:10]


# ============ 工具函数 ============

def _run_lark(args_list, json_input=None):
    """运行 lark-cli 命令"""
    # 处理JSON输入：写入临时文件
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

    # 清理临时文件
    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # 方法1: 直接运行 .cmd 文件（Python 在 Windows 上会自动通过 cmd.exe 执行）
    cli_cmd = LARK_CLI.replace("lark-cli", "lark-cli.cmd")
    if not cli_cmd.endswith(".cmd"):
        # 如果原路径不是 .cmd，查找配套的 .cmd 文件
        alt_path = LARK_CLI + ".cmd"
        if os.path.exists(alt_path):
            cli_cmd = alt_path
        else:
            # 从 workspace node_modules 找
            ws_cmd = os.path.join(
                os.path.dirname(LARK_CLI), "..", "workspace",
                "node_modules", ".bin", "lark-cli.cmd"
            )
            if os.path.exists(ws_cmd):
                cli_cmd = ws_cmd
    try:
        # 合并 args, 直接传列表
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


def parse_date_str(s):
    """解析日期，支持 yyyy/MM/dd 和 yyyy-MM-dd"""
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    return s


# ============ 核心逻辑 ============

def load_energy_context(today=None):
    """读取当天精力状态上下文。

    兼容旧的手动 #精力 文件，也保留 Garmin 同步写入的扩展字段。
    """
    if not os.path.exists(ENERGY_STATUS_FILE):
        return None
    try:
        with open(ENERGY_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 只取当天的记录
        if data.get("date") == _today_iso(today):
            return data
    except (json.JSONDecodeError, IOError):
        pass
    return None


def load_energy_status(today=None):
    """读取精力状态记录"""
    context = load_energy_context(today=today)
    if context:
        return context.get("status")
    return None


def resolve_energy_multiplier(energy_context, config):
    """根据精力上下文解析排程系数，手动配置优先。"""
    if "精力系数" in config:
        return float(config["精力系数"])

    if energy_context:
        coefficient = energy_context.get("energy_coefficient")
        if coefficient is not None:
            return float(coefficient)
        status = energy_context.get("status")
        if status == "差":
            return 0.8
        if status == "好":
            return 1.2

    return float(config.get("精力系数", 1.0))


def _read_body_os_config():
    """读取 Body OS 配置，获取 scheduler_control_level。"""
    try:
        with open(BODY_OS_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("policy", {}).get("scheduler_control_level", 1)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return 1


def _update_task_deadline_in_base(record_id: str, new_deadline: str, note: str = ""):
    """更新飞书 Base 中一条任务记录的截止日期和备注。"""
    if not record_id:
        return
    patch = {"截止日期": new_deadline}
    if note:
        patch["备注"] = note
    json_input = json.dumps({
        "record_id_list": [record_id],
        "patch": patch,
    }, ensure_ascii=False)
    args = [
        "base", "+record-batch-update",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["执行库"],
        "--json", "@_record_json",
        "--as", "user",
    ]
    resp = _run_lark(args, json_input=json_input)
    if resp.returncode == 0:
        print(f"  ✅ Body OS L2：任务 {record_id[:8]}... 已延期至 {new_deadline}")
    else:
        print(f"  [WARN] Body OS L2 更新失败：{resp.stderr or resp.stdout}")


def adjust_tasks_for_energy_policy(tasks, energy_context, dry_run=False):
    """根据 Body OS 学习负载建议调整任务优先级。

    L1（control_level=1）：只返回调整建议，不写飞书。
    L2（control_level>=2）：自动更新飞书 Base 中的任务截止日和备注。
    """
    control_level = _read_body_os_config()
    study_load = (energy_context or {}).get("study_load")
    adjusted = []
    overflow = []

    for task in tasks:
        item = dict(task)
        priority = str(item.get("priority", ""))
        energy = item.get("energy")
        is_p0 = priority.startswith("P0")

        if study_load == "recovery":
            if energy == "高" and not is_p0:
                item["defer_reason"] = "Body OS恢复/维护日，非关键高精力任务建议后移。"
                overflow.append(item)
                continue
            if energy == "高" and is_p0:
                item["body_os_note"] = "P0任务保留，但建议拆小块并降低连续专注时长。"
        elif study_load == "deep":
            if energy == "高":
                item["weight"] = min(120, int(item.get("weight", 0) or 0) + 15)
                item["body_os_note"] = "身体状态支持深度学习，高精力任务优先。"

        adjusted.append(item)

    # L2: 自动写飞书 Base
    if control_level >= 2 and not dry_run and overflow:
        today_dt = date.today()
        tomorrow = (today_dt + timedelta(days=1)).strftime("%Y/%m/%d")
        for task in overflow:
            record_id = task.get("record_id")
            if record_id:
                _update_task_deadline_in_base(
                    record_id, tomorrow,
                    f"Body OS 恢复日自动延期：{task.get('defer_reason', '')}",
                )

    adjusted.sort(key=lambda item: (-int(item.get("weight", 0) or 0), item.get("title", "")))
    overflow.sort(key=lambda item: (-int(item.get("weight", 0) or 0), item.get("title", "")))
    l1_only = control_level < 2
    msg = (
        "Body OS 仅提供任务优先级与后移建议，真正改日历需确认。"
        if l1_only
        else "Body OS 已自动调整任务优先级，溢出任务已延后。"
    )
    return {
        "tasks": adjusted,
        "overflow": overflow,
        "study_load": study_load,
        "l1_only": l1_only,
        "control_level": control_level,
        "message": msg,
    }


def save_energy_status(status_text):
    """保存精力状态记录"""
    # 解析状态
    if any(w in status_text for w in ["很差", "不好", "差劲"]):
        level = "差"
    elif any(w in status_text for w in ["一般", "还行"]):
        level = "一般"
    elif any(w in status_text for w in ["好", "不错", "很好"]):
        level = "好"
    else:
        level = "一般"

    data = {
        "date": date.today().isoformat(),
        "status": level,
        "raw": status_text
    }
    with open(ENERGY_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return level


def get_today_tasks(target_date=None):
    """从执行库获取今日待办任务"""
    if target_date is None:
        target_date = date.today().strftime("%Y/%m/%d")

    # JSON 格式返回 data.fields(字段名列表) + data.data(位置数组)
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["执行库"],
        "--as", "user",
        "--limit", "100",
        "--format", "json",
    ])

    if not result.get("ok"):
        print(f"[ERROR] 读取执行库失败: {result.get('error')}")
        return []

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])
    record_ids = d.get("record_id_list", [])

    tasks = []
    for idx, row in enumerate(data_array):
        fields = dict(zip(field_names, row))
        fields["_record_id"] = record_ids[idx] if idx < len(record_ids) else ""
        task = _parse_task_row(fields, target_date)
        if not task.get("_skip"):
            del task["_skip"]
            tasks.append(task)

    # 排序：权重降序 → 硬骨头优先 → 截止日期升序
    def sort_key(t):
        return (-t["weight"], 0 if t["is_tough"] else 1, t.get("deadline") or "Z")

    tasks.sort(key=sort_key)
    return tasks


def _parse_task_row(fields, target_date):
    """解析一行任务数据"""
    def _get(field_name, default=None):
        val = fields.get(field_name, default)
        if isinstance(val, list):
            return val[0] if val else default
        return val

    title = _get("标题", "(无标题)")
    status = _get("状态")
    deadline = _get("截止日期", "")
    project = _get("所属项目")
    priority = _get("轻重缓急", "P3-不重要不紧急")
    energy = _get("精力消耗等级", "中")
    est_time = _get("预估耗时", 30)
    is_tough = fields.get("是否为今日硬骨头", False) or False
    category = _get("科目类别")
    record_id = fields.get("_record_id", fields.get("record_id", ""))

    # 筛选：今天截止 或 状态=进行中/待排期/待收集
    is_today_deadline = False
    if deadline:
        dl_str = str(deadline)[:10].replace("-", "/")
        is_today_deadline = dl_str == target_date[:10].replace("-", "/")

    skip = not (is_today_deadline or status in ["进行中", "待排期", "待收集"])
    if status in ["已完成", "已归档"]:
        skip = True

    weight = PRIORITY_WEIGHT.get(priority, 40)

    return {
        "record_id": record_id,
        "title": title,
        "project": project or "",
        "priority": priority,
        "weight": weight,
        "energy": energy,
        "est_time": int(est_time) if est_time else 30,
        "is_tough": bool(is_tough),
        "deadline": deadline or "",
        "category": category or "",
        "status": status or "待收集",
        "_skip": skip,
    }


def get_subject_baselines():
    """读取科目进度基线"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["科目进度基线"],
        "--as", "user",
        "--limit", "20",
        "--format", "json",
    ])

    if not result.get("ok"):
        return {}

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])

    baselines = {}
    for row in data_array:
        fields = dict(zip(field_names, row))

        def _get(fn, default=None):
            v = fields.get(fn, default)
            if isinstance(v, list):
                return v[0] if v else default
            return v

        subject = _get("科目")
        if not subject:
            continue
        baselines[subject] = {
            "total_goal": _get("总目标", ""),
            "completion_rate": _get("当前完成率", 0) or 0,
            "daily_hours": float(_get("平均每天应投入小时数", 0) or 0),
            "exam_date": _get("考试日期", ""),
            "countdown": _get("倒计时", None),
        }
    return baselines


def generate_schedule(tasks, baselines, target_date=None, dry_run=False):
    """生成作战时间轴（新版：高效+完整+零散三层结构）"""
    if target_date is None:
        target_date = date.today().strftime("%Y/%m/%d")

    # 检查精力状态 + 自定义配置
    config = load_config()
    energy_context = load_energy_context(today=target_date)
    energy_status = energy_context.get("status") if energy_context else None

    base_hours = float(config.get("今日可用时长", DEFAULT_DAILY_HOURS))
    energy_multiplier = resolve_energy_multiplier(energy_context, config)
    available_hours = max(4.0, min(14.0, base_hours * energy_multiplier))

    # 科目偏差驱动的动态权重 boost
    subject_gap = {}
    for cat, bl in baselines.items():
        completion = bl.get("completion_rate", 0) / 100.0 if bl.get("completion_rate") else 0
        expected = bl.get("daily_hours", 0)
        if expected > 0:
            # 距考试还有天数
            exam_bl = bl.get("exam_date", "")
            days_left = 999
            if exam_bl:
                try:
                    dl_str = str(exam_bl)[:10].replace("-", "/")
                    exam_dt = datetime.strptime(dl_str, "%Y/%m/%d").date()
                    days_left = (exam_dt - date.today()).days
                except ValueError:
                    pass
            if days_left > 0:
                # 理论完成率 = (剩余天数 / 总天数) * 100%，实际完成率差距越大 → 越需要补课
                total_days = 365  # 粗略估计从1月1日开始
                theoretical_completion = max(0, min(1, (total_days - (date.today().timetuple().tm_yday)) / total_days))
                gap = max(0, theoretical_completion - completion)
                subject_gap[cat] = gap

    def apply_baseline_boost(tasks):
        """根据科目缺口提升任务权重"""
        boosted = []
        for t in tasks:
            new_task = t.copy()
            cat = t.get("category", "")
            if cat in subject_gap:
                gap = subject_gap[cat]
                if gap > 0.1:
                    # 差距 > 10%，权重+20；差距 > 30%，权重+40
                    boost = min(50, int(gap * 150))
                    new_task["weight"] = min(100, t["weight"] + boost)
            boosted.append(new_task)
        return boosted

    all_tasks = apply_baseline_boost(tasks)

    # 分配任务到三层
    # 排序：权重降序 → 硬骨头优先
    def sort_key(t):
        return (-t["weight"], 0 if t["is_tough"] else 1)

    all_tasks = sorted(tasks, key=sort_key)

    # 构建时间轴
    timeline = []
    total_assigned = 0
    overflow = []

    all_pending = all_tasks[:]
    assigned_ids = set()

    for name, start, end, energy, mode, note in SLOT_LAYOUT:
        if energy is None:
            continue

        slot_minutes = _calc_slot_minutes(start, end)

        # 优先取对应精力等级的任务
        candidates = [t for t in all_pending if t["record_id"] not in assigned_ids and t["energy"] == energy]
        candidates.sort(key=sort_key)

        # 如果该精力等级没有任务，从待分配池补位
        if not candidates:
            candidates = [t for t in all_pending if t["record_id"] not in assigned_ids]
            candidates.sort(key=sort_key)

        items = []
        used = 0
        for t in candidates:
            if t["record_id"] in assigned_ids:
                continue
            if used + t["est_time"] > slot_minutes:
                continue
            items.append(t)
            assigned_ids.add(t["record_id"])
            used += t["est_time"]
            total_assigned += t["est_time"]

        if items:
            timeline.append({
                "slot": name,
                "time": f"{start}-{end}",
                "energy": energy,
                "mode": mode,
                "note": note,
                "tasks": items,
                "total_minutes": used,
            })

    # 所有时段跑完后，剩余未分配的是溢出
    overflow = [t for t in tasks if t["record_id"] not in assigned_ids]

    # 科目偏差检查
    risks = []
    subject_stats = {}
    for t in tasks:
        cat = t.get("category", "")
        if cat and cat in baselines:
            if cat not in subject_stats:
                subject_stats[cat] = {"actual_minutes": 0}
            subject_stats[cat]["actual_minutes"] += t["est_time"]

    for cat, stats in subject_stats.items():
        planned = stats["actual_minutes"] / 60
        expected = baselines.get(cat, {}).get("daily_hours", 0)
        if expected > 0 and planned < expected * 0.5:
            risks.append(f"⚠ {cat}：今日仅安排 {planned:.1f}h，建议 {expected}h，偏少")

    stale_ideas = get_stale_ideas()

    # 🆕 习惯查询
    habits = query_habits()

    # v2.0 新增模块查询
    core_event = get_core_event(tasks)
    social_reminders = query_social_reminders()
    finance_summary = query_finance_summary()
    creation_progress = query_creation_progress()
    knowledge_stats = query_knowledge_stats()

    # 🆕 深度工作统计
    # 计算深度工作时长（高效段①+② 总时长）
    deep_work_minutes = 0
    for slot in timeline:
        if slot["mode"] and "深度" in slot["mode"]:
            deep_work_minutes += slot["total_minutes"]
    # 从 timeline 收集已分配的任务对象列表
    assigned_tasks = []
    for slot in timeline:
        assigned_tasks.extend(slot.get("tasks", []))
    # 计算冲刺任务数
    sprint_tasks = [t for t in assigned_tasks if t["title"].startswith("🔥") or t.get("is_tough")]

    # 🆕 4DX计分板（本周累计深度小时）
    weekly_deep_hours = compute_4dx_scoreboard(target_date)

    # 🆕 第一勺冰淇淋：今日最重要的一件事（在处理任何消息前完成）
    first_scoop = core_event

    # 🆕 浮浅工作预算计算
    shallow_minutes = 0
    for slot in timeline:
        if slot.get("mode") and "浮浅" in slot.get("mode", ""):
            shallow_minutes += slot.get("total_minutes", 0)
    shallow_ratio = 0
    total_work_minutes = deep_work_minutes + shallow_minutes
    if total_work_minutes > 0:
        shallow_ratio = round(shallow_minutes / total_work_minutes * 100)

    # 🆕 拖延根因诊断（连续3天+的overflow任务）
    overflow_streaks = track_overflow_streaks(overflow, target_date)

    # 🆕 ART恢复建议
    art_recovery = get_art_recovery_suggestion(deep_work_minutes)

    return {
        "date": target_date,
        "available_hours": round(available_hours, 1),
        "energy_status": energy_status or "正常",
        "energy_context": energy_context or {},
        "timeline": timeline,
        "overflow": overflow,
        "total_tasks": len(tasks),
        "assigned_tasks": len(assigned_ids),
        "total_minutes": total_assigned,
        "risks": risks,
        "tough_tasks": [t for t in tasks if t["is_tough"]],
        "stale_ideas": stale_ideas,
        # v2.0 新增
        "core_event": core_event,
        "social_reminders": social_reminders,
        "finance_summary": finance_summary,
        "creation_progress": creation_progress,
        "knowledge_stats": knowledge_stats,
        # 🆕 深度工作
        "deep_work_minutes": deep_work_minutes,
        "sprint_tasks": sprint_tasks,
        "weekly_deep_hours": weekly_deep_hours,
        # 🆕 习惯追踪
        "habits": habits,
        # 🆕 深度工作优化（P0+P1）
        "first_scoop": first_scoop,
        "shallow_minutes": shallow_minutes,
        "shallow_ratio": shallow_ratio,
        "overflow_streaks": overflow_streaks,
        "art_recovery": art_recovery,
    }


def compute_4dx_scoreboard(target_date_str):
    """计算4DX计分板：本周累计深度工作小时数
    
    从深度工作追踪表读取本周记录，累加深度工作时长
    """
    try:
        # 获取本周一和本周末
        from datetime import date, timedelta
        if target_date_str and "/" in target_date_str:
            parts = target_date_str.split("/")
            td = date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            td = date.today()
        monday = td - timedelta(days=td.weekday())
        sunday = monday + timedelta(days=6)
        
        # 读取深度工作追踪表
        result = _lark_json([
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLES["深度工作追踪表"],
            "--as", "user",
            "--limit", "50",
            "--format", "json",
        ])
        
        if not result.get("ok"):
            return 0
        
        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        
        total_deep = 0
        for row in data_array:
            fields = dict(zip(field_names, row))
            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v
            dr = _get("日期", "")
            if dr:
                try:
                    dr_date = datetime.strptime(str(dr)[:10], "%Y/%m/%d").date()
                    if monday <= dr_date <= sunday:
                        dm = _get("当日深度工作时长(min)", 0) or 0
                        total_deep += int(dm)
                except (ValueError, TypeError):
                    pass
        
        return round(total_deep / 60, 1)
    except Exception:
        return 0


def auto_fill_deep_work_record(schedule, target_date_str, dry_run=False):
    """排程后自动预填深度工作记录（仅当今日无手动记录时）

    逻辑：
    1. 从 schedule 取计划深度时长
    2. 查询今日基础表是否已有手动录入
    3. 有用户主动录入 → 跳过（不覆盖）
    4. 无记录或只有预填 → 写入/更新计划值
    
    灵活性：多次调度会更新预填值，适应精力变化导致日程调整
    """
    deep_minutes = schedule.get("deep_work_minutes", 0)
    if deep_minutes <= 0:
        return  # 今日无深度安排，不预填

    if dry_run:
        print(f"  [DRY-RUN] 深度工作预填：{deep_minutes//60}h{deep_minutes%60}m（不写入）")
        return

    # 读取今日 Base 记录
    today_str = target_date_str or date.today().strftime("%Y/%m/%d")
    try:
        result = _lark_json([
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLES["深度工作追踪表"],
            "--as", "user",
            "--limit", "50",
            "--format", "json",
        ])
        if not result.get("ok"):
            print(f"  [WARN] 深度预填：查询Base失败，跳过")
            return

        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        record_ids = d.get("record_id_list", [])

        # 找今天是否有手动记录
        existing_record_id = None
        has_user_data = False
        for idx, row in enumerate(data_array):
            fields = dict(zip(field_names, row))
            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v

            dr = _get("日期", "")
            if dr:
                dr_normalized = str(dr)[:10].replace("-", "/")
                if dr_normalized == today_str[:10].replace("-", "/"):
                    existing_record_id = record_ids[idx] if idx < len(record_ids) else ""
                    # 检查是否有用户手动录入的字段（心流/干扰/备注等）
                    has_flow = bool(_get("最高心流状态", ""))
                    has_distractions = _get("干扰次数", None) is not None
                    if has_flow or has_distractions:
                        has_user_data = True
                    break

        # 构造预填数据
        record = {
            "日期": today_str,
            "当日深度工作时长(min)": deep_minutes,
        }

        if existing_record_id and has_user_data:
            # 用户已有手动记录 → 跳过，不覆盖
            print(f"  [SKIP] 深度预填跳过：今日已有手动记录（{deep_minutes//60}h{deep_minutes%60}m）")
            return

        if existing_record_id:
            # 只有预填或空记录 → 更新
            json_input = json.dumps({
                "record_id_list": [existing_record_id],
                "patch": record,
            }, ensure_ascii=False)
            args = [
                "base", "+record-batch-update",
                "--base-token", BASE_TOKEN,
                "--table-id", TABLES["深度工作追踪表"],
                "--json", "@_record_json",
                "--as", "user",
            ]
        else:
            # 无记录 → 新建
            json_input = json.dumps(record, ensure_ascii=False)
            args = [
                "base", "+record-upsert",
                "--base-token", BASE_TOKEN,
                "--table-id", TABLES["深度工作追踪表"],
                "--json", "@_record_json",
                "--as", "user",
            ]

        resp = _run_lark(args, json_input=json_input)
        if resp.returncode == 0:
            print(f"  ✅ 深度工作预填：计划{deep_minutes//60}h{deep_minutes%60}m")
        else:
            print(f"  [WARN] 深度工作预填失败：{resp.stderr or resp.stdout}")

    except Exception as e:
        print(f"  [WARN] 深度工作预填异常：{e}")


def _calc_slot_minutes(start, end):
    """计算时段可用分钟数"""
    def to_min(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    return to_min(end) - to_min(start)


def get_core_event(tasks):
    """获取今日核心事件（硬骨头权重最高者，或P0截止最近者）"""
    tough = [t for t in tasks if t["is_tough"]]
    if tough:
        tough.sort(key=lambda t: (-t["weight"], t.get("deadline") or "Z"))
        return tough[0]
    # 无硬骨头，取P0中截止最近的
    p0 = [t for t in tasks if t["priority"] == "P0-重要紧急"]
    if p0:
        p0.sort(key=lambda t: t.get("deadline") or "Z")
        return p0[0]
    # 取权重最高的
    if tasks:
        tasks_sorted = sorted(tasks, key=lambda t: -t["weight"])
        return tasks_sorted[0]
    return None


def query_social_reminders():
    """查询社交提醒：生日未来7天 + 久未联系 >14天"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["社交关系表"],
        "--as", "user",
        "--limit", "100",
        "--format", "json",
    ])
    if not result.get("ok"):
        return {"birthdays": [], "stale_contacts": []}

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])
    now = datetime.now()

    # 按联系人聚合
    contacts = {}
    for row in data_array:
        fields = dict(zip(field_names, row))
        def _get(fn, default=None):
            v = fields.get(fn, default)
            if isinstance(v, list):
                return v[0] if v else default
            return v
        name = _get("联系人", "")
        if not name:
            continue
        if name not in contacts:
            contacts[name] = {"birthday": None, "last_date": None, "亲密度": "★★"}
        # 生日
        bday = _get("生日", "")
        if bday:
            contacts[name]["birthday"] = str(bday)[:5]  # MM-DD
        # 最近日期
        dt = _get("日期", "")
        if dt:
            dt_str = str(dt)[:10]
            if contacts[name]["last_date"] is None or dt_str > contacts[name]["last_date"]:
                contacts[name]["last_date"] = dt_str
        # 亲密度
        intimacy = _get("亲密度", "★★")
        if intimacy:
            contacts[name]["亲密度"] = intimacy

    # 查生日提醒（未来7天）
    birthdays = []
    for name, info in contacts.items():
        if info.get("birthday"):
            try:
                b_mmdd = info["birthday"]
                b_this_year = f"{now.year}-{b_mmdd}"
                b_date = datetime.strptime(b_this_year, "%Y-%m-%d")
                days_until = (b_date - now).days
                if 0 <= days_until <= 7:
                    birthdays.append({"name": name, "days_until": days_until, "date": b_mmdd})
            except ValueError:
                pass

    # 查久未联系 >阈值（自适应：亲密的人阈值更低，普通关系阈值更高）
    stale_contacts = []
    for name, info in contacts.items():
        if info.get("last_date"):
            try:
                last = datetime.strptime(info["last_date"], "%Y-%m-%d")
                days_since = (now - last).days
                
                # 根据亲密度自适应阈值
                intimacy = info.get("亲密度", "★★")
                if intimacy == "★★★":
                    threshold = 7  # 亲密：7天没联系就提醒
                elif intimacy == "★★":
                    threshold = 14  # 中等：14天
                else:
                    threshold = 30  # 泛泛：30天
                
                if days_since >= threshold:
                    stale_contacts.append({
                        "name": name,
                        "days_since": days_since,
                        "threshold": threshold,
                    })
            except ValueError:
                pass

    return {"birthdays": birthdays, "stale_contacts": stale_contacts}


def query_finance_summary():
    """查询当月财务汇总"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["财务流水表"],
        "--as", "user",
        "--limit", "200",
        "--format", "json",
    ])
    if not result.get("ok"):
        return {}

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])
    now = datetime.now()
    month_prefix = now.strftime("%Y/%m")

    categories = {}
    for row in data_array:
        fields = dict(zip(field_names, row))
        def _get(fn, default=None):
            v = fields.get(fn, default)
            if isinstance(v, list):
                return v[0] if v else default
            return v
        date_str = str(_get("日期", ""))
        if not date_str.startswith(month_prefix):
            continue
        expense_type = _get("类型", "支出")
        category = _get("分类", "其他")
        amount = _get("金额", 0) or 0
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            amount = 0
        if expense_type == "支出":
            categories[category] = categories.get(category, 0) + amount

    total = sum(categories.values())
    # 按金额排序取TOP5
    top = sorted(categories.items(), key=lambda x: -x[1])[:5]
    return {"total": round(total, 1), "categories": dict(top)}


def query_creation_progress():
    """查询创作进展（进行中的作品 + 灵感池未处理条数）"""
    in_progress = []
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["创作素材表"],
        "--as", "user",
        "--limit", "50",
        "--format", "json",
    ])
    if result.get("ok"):
        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        for row in data_array:
            fields = dict(zip(field_names, row))
            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v
            status = _get("状态", "")
            if status == "进行中":
                title = _get("标题", "(无标题)")
                ctype = _get("类型", "")
                in_progress.append({"title": title, "type": ctype})

    return {"in_progress": in_progress}


def query_knowledge_stats():
    """查询知识笔记统计（今日新增 + MOC数量）"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["知识笔记表"],
        "--as", "user",
        "--limit", "100",
        "--format", "json",
    ])
    today_new = []
    moc_count = 0
    if result.get("ok"):
        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        today_str = date.today().strftime("%Y-%m-%d")
        for row in data_array:
            fields = dict(zip(field_names, row))
            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v
            note_type = _get("类型", "")
            if note_type == "MOC":
                moc_count += 1
            created = _get("创建时间", "")
            if created and str(created)[:10] == today_str:
                title = _get("标题", "(无标题)")
                cat = _get("分类", "")
                today_new.append({"title": title, "category": cat})

    return {"today_new": today_new, "moc_count": moc_count}


def query_habits():
    """查询习惯追踪表：获取进行中的习惯及其进度"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["习惯追踪表"],
        "--as", "user",
        "--limit", "50",
        "--format", "json",
    ])
    if not result.get("ok"):
        return []
    
    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])
    
    habits = []
    for row in data_array:
        fields = dict(zip(field_names, row))
        def _get(fn, default=None):
            v = fields.get(fn, default)
            return v[0] if isinstance(v, list) and v else (v or default)
        
        if _get("状态") == "进行中":
            habits.append({
                "name": _get("习惯名称", ""),
                "streak": int(_get("当前连续天数", 0) or 0),
                "best": int(_get("历史最佳", 0) or 0),
                "total": int(_get("总打卡次数", 0) or 0),
                "identity": _get("身份声明", ""),
            })
    
    return habits


def get_stale_ideas():
    """获取超过3天未处理的灵感"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["灵感库"],
        "--as", "user",
        "--limit", "50",
        "--format", "json",
    ])

    if not result.get("ok"):
        return []

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])
    now = datetime.now()
    stale = []

    for row in data_array:
        fields = dict(zip(field_names, row))

        def _get(fn, default=None):
            v = fields.get(fn, default)
            if isinstance(v, list):
                return v[0] if v else default
            return v

        status = _get("转化状态")
        if status and status != "待孵化":
            continue

        title = _get("标题", "(无标题)")
        created = _get("创建时间", "")

        if created and len(str(created)) >= 10:
            try:
                c_time = datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
                if (now - c_time).days >= 3:
                    stale.append({"title": title, "days": (now - c_time).days, "created": str(created)[:10]})
            except ValueError:
                pass

    return stale


def track_overflow_streaks(overflow_tasks, target_date):
    """追踪连续溢出任务，检测拖延模式
    
    读取历史溢出记录，更新连续天数，返回连续3天以上的慢性拖延任务。
    """
    tracker_file = os.path.join(os.path.dirname(__file__), "runtime", "_overflow_tracker.json")
    
    history = {}
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    today_key = target_date.replace("/", "-") if target_date else date.today().isoformat()
    current_overflow_titles = set(t["title"] for t in overflow_tasks)
    
    # 清理超过7天没出现的记录
    new_history = {}
    for title, data in history.items():
        last_seen = data.get("last_seen", "")
        try:
            last_dt = datetime.strptime(last_seen, "%Y-%m-%d").date()
            if (date.today() - last_dt).days <= 7:
                new_history[title] = data
        except ValueError:
            pass
    
    # 更新当前overflow
    for title in current_overflow_titles:
        if title in new_history:
            new_history[title]["streak"] += 1
            new_history[title]["last_seen"] = today_key
        else:
            new_history[title] = {"streak": 1, "last_seen": today_key}
    
    # 非overflow的任务重置streak
    for title in list(new_history.keys()):
        if title not in current_overflow_titles and new_history[title].get("last_seen") == today_key:
            pass  # 不重置，只清理过期的
    
    os.makedirs(os.path.dirname(tracker_file), exist_ok=True)
    with open(tracker_file, "w", encoding="utf-8") as f:
        json.dump(new_history, f, ensure_ascii=False, indent=2)
    
    # 返回连续3天以上的
    chronic = []
    for title, data in new_history.items():
        if data["streak"] >= 3 and title in current_overflow_titles:
            chronic.append({"title": title, "streak": data["streak"]})
    
    return chronic


def get_art_recovery_suggestion(deep_minutes):
    """根据深度工作时长生成ART(注意力恢复理论)建议"""
    if deep_minutes >= 180:
        return {
            "level": "high",
            "suggestions": [
                "午休后散步15-20min（接触自然光和绿色植物）",
                "晚间做手工/绘画/阅读纸质书（非屏幕活动）",
                "避免：刷短视频不是恢复，是消耗",
            ]
        }
    elif deep_minutes >= 90:
        return {
            "level": "medium",
            "suggestions": [
                "午后闭眼休息10min或散步10min",
                "避免连续看屏幕超过2h",
            ]
        }
    else:
        return {
            "level": "low",
            "suggestions": [
                "今日深度不足，保持正常休息即可",
            ]
        }


def format_schedule(schedule):
    """格式化为推送文本（新版：含高效+完整+零散标注）"""
    lines = []
    d = schedule["date"]
    lines.append(f"📋 【{d} 今日时间轴】")
    lines.append(f"⏱ 今日可用：{schedule['available_hours']:.1f}h | 精力状态：{schedule['energy_status']}")
    lines.append(f"📊 今日任务：{schedule['assigned_tasks']}/{schedule['total_tasks']} 项已排入")
    lines.append("")

    for slot in schedule["timeline"]:
        icon = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(slot["energy"], "⚪")
        mode_tag = f" {slot.get('mode', '')}" if slot.get('mode') else ""
        note = slot.get("note", "")
        lines.append(f"{icon}{mode_tag} {slot['slot']}（{slot['time']}）· {note}")
        for t in slot["tasks"]:
            mark = "⭐ " if t["is_tough"] else "  "
            lines.append(f"  {mark}{t['title']}（{t['est_time']}分钟）")
        lines.append("")

    # 硬骨头提醒
    if schedule["tough_tasks"]:
        lines.append("⭐ 【硬骨头提醒】")
        for t in schedule["tough_tasks"]:
            lines.append(f"  今日必啃：{t['title']}")
        lines.append("")

    # 风险预警
    if schedule["risks"]:
        lines.append("⚠️ 【风险预警】")
        for r in schedule["risks"]:
            lines.append(f"  {r}")
        lines.append("")

    # 超载提醒
    if schedule["overflow"]:
        lines.append("📦 【已移至明日】")
        for t in schedule["overflow"]:
            lines.append(f"  · {t['title']}（{t['est_time']}min）- {t['priority']}")
        lines.append("")

    # 灵感冷处理
    if schedule["stale_ideas"]:
        lines.append("💡 【灵感冷处理（>3天未处理）】")
        for idea in schedule["stale_ideas"][:5]:
            lines.append(f"  · {idea['title']}（{idea['days']}天前）")
        if len(schedule["stale_ideas"]) > 5:
            lines.append(f"  ... 还有 {len(schedule['stale_ideas']) - 5} 条")
        lines.append("")

    return "\n".join(lines)


def format_schedule_v2(schedule):
    """格式化为推送文本（v2.0 全模块 + 进度条增强版）"""
    lines = []
    d = schedule["date"]
    lines.append(f"╔══════════════════════════════════════╗")
    lines.append(f"║        🎯 {d} 作战时间轴              ║")
    lines.append(f"╠══════════════════════════════════════╣")
    
    # 进度条可视化
    if schedule["total_tasks"] > 0:
        assigned_ratio = schedule["assigned_tasks"] / schedule["total_tasks"]
        bar_width = 20
        filled = int(bar_width * assigned_ratio)
        bar = "█" * filled + "░" * (bar_width - filled)
        lines.append(f"║  任务进度：{bar} {assigned_ratio:.0%}         ║")
    lines.append(f"⏱ 今日可用：{schedule['available_hours']:.1f}h | 精力：{schedule['energy_status']}")
    lines.append(f"📊 任务：{schedule['assigned_tasks']}/{schedule['total_tasks']} 项已排入")
    lines.append("")

    # 🆕 第一勺冰淇淋（在核心事件之前，最优先）
    first_scoop = schedule.get("first_scoop")
    if first_scoop:
        lines.append(f"🍦 【第一勺冰淇淋】先做：{first_scoop['title']}")
        lines.append("   ⚠️ 在处理任何消息/飞书/微信前完成！")
        lines.append("")

    # 🎯 核心事件
    core = schedule.get("core_event")
    if core:
        lines.append(f"🎯 【核心事件】今日必完成：{core['title']}")
        lines.append("   （完成它就值得了！）")
        lines.append("")

    # 时间轴
    for slot in schedule["timeline"]:
        icon = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(slot["energy"], "⚪")
        mode_tag = f" {slot.get('mode', '')}" if slot.get('mode') else ""
        note = slot.get("note", "")
        lines.append(f"{icon}{mode_tag} {slot['slot']}（{slot['time']}）· {note}")
        for t in slot["tasks"]:
            mark = "⭐ " if t["is_tough"] else "  "
            # 🆕 冲刺任务标记
            sprint_mark = "🔥 " if t["title"].startswith("🔥") else ""
            lines.append(f"  {mark}{sprint_mark}{t['title']}（{t['est_time']}分钟）")
        lines.append("")

    # 硬骨头提醒
    if schedule["tough_tasks"]:
        lines.append("⭐ 【硬骨头提醒】")
        for t in schedule["tough_tasks"]:
            lines.append(f"  今日必啃：{t['title']}")
        lines.append("")

    # 风险预警
    if schedule["risks"]:
        lines.append("⚠️ 【风险预警】")
        for r in schedule["risks"]:
            lines.append(f"  {r}")
        lines.append("")

    # 超载提醒
    if schedule["overflow"]:
        lines.append("📦 【已移至明日】")
        for t in schedule["overflow"]:
            lines.append(f"  · {t['title']}（{t['est_time']}min）- {t['priority']}")
        lines.append("")

    # 🆕 拖延根因诊断（连续3天+未完成）
    chronic = schedule.get("overflow_streaks", [])
    if chronic:
        lines.append("🚨 【拖延根因诊断】")
        for c in chronic:
            lines.append(f"  「{c['title']}」已连续{c['streak']}天未完成")
            lines.append(f"    → 不是时间不够，是在逃避。请检查：")
            lines.append(f"    · 时间有限：害怕投入后发现做不好？")
            lines.append(f"    · 能力有限：害怕面对自己的平庸？")
            lines.append(f"    💡 破局：接纳「我就是有限的」→ 硬着头皮开始5分钟")
        lines.append("")

    # 🤝 社交提醒
    social = schedule.get("social_reminders", {})
    social_lines = []
    for b in social.get("birthdays", []):
        if b["days_until"] == 0:
            social_lines.append(f"🎂 {b['name']} 今天生日！记得发消息")
        else:
            social_lines.append(f"🎂 {b['name']} 还有{b['days_until']}天生日（{b['date']}）")
    for s in social.get("stale_contacts", []):
        threshold = s.get("threshold", 14)
        if s["days_since"] == threshold:
            social_lines.append(f"🤝 {s['name']}：已{s['days_since']}天没联系（阈值{threshold}天）")
        else:
            social_lines.append(f"🤝 {s['name']}：已{s['days_since']}天没联系")
    if social_lines:
        lines.append("🤝 【社交提醒】")
        for sl in social_lines[:5]:
            lines.append(f"  {sl}")
        lines.append("")

    # 💰 财务概览
    finance = schedule.get("finance_summary", {})
    if finance.get("total", 0) > 0:
        lines.append("💰 【财务概览】")
        for cat, amount in finance.get("categories", {}).items():
            lines.append(f"  · {cat}：{amount:.0f}元")
        lines.append(f"  📊 本月合计：{finance['total']:.0f}元")
        lines.append("")

    # 🎨 创作进展
    creation = schedule.get("creation_progress", {})
    if creation.get("in_progress"):
        lines.append("🎨 【创作进展】")
        for c in creation["in_progress"][:5]:
            lines.append(f"  · {c['title']}（{c['type']}）")
        lines.append("")

    # 📝 知识笔记
    knowledge = schedule.get("knowledge_stats", {})
    if knowledge.get("today_new") or knowledge.get("moc_count", 0) > 0:
        lines.append("📝 【知识笔记】")
        for n in knowledge.get("today_new", []):
            lines.append(f"  · {n['title']}（{n.get('category','')}）")
        if knowledge.get("moc_count", 0) > 0:
            lines.append(f"  🗺 MOC导航图：{knowledge['moc_count']}个")
        lines.append("")

    # 💡 灵感冷处理
    if schedule["stale_ideas"]:
        lines.append("💡 【灵感冷处理（>3天未处理）】")
        for idea in schedule["stale_ideas"][:5]:
            lines.append(f"  · {idea['title']}（{idea['days']}天前）")
        if len(schedule["stale_ideas"]) > 5:
            lines.append(f"  ... 还有 {len(schedule['stale_ideas']) - 5} 条")
        lines.append("")

    # 🆕 🔴 深度工作模块
    dw_minutes = schedule.get("deep_work_minutes", 0)
    weekly_dw = schedule.get("weekly_deep_hours", 0)
    sprint_tasks = schedule.get("sprint_tasks", [])
    
    lines.append("🔴 【深度工作指南】")
    if dw_minutes > 0:
        lines.append(f"  · 📅 今日深度时段：{dw_minutes//60}h{dw_minutes%60}m")
    # 🆕 浮浅预算
    shallow_ratio = schedule.get("shallow_ratio", 0)
    shallow_minutes = schedule.get("shallow_minutes", 0)
    if shallow_ratio > 0 or shallow_minutes > 0:
        budget_status = "✅" if shallow_ratio <= 30 else "⚠️超预算！"
        lines.append(f"  · 📊 浮浅预算：{shallow_minutes//60}h{shallow_minutes%60}m = {shallow_ratio}% {budget_status}")
    # 4DX计分板
    weekly_target = 25.0  # 默认目标：每周25h深度工作
    if weekly_dw > 0:
        ratio = min(1.0, weekly_dw / weekly_target)
        bar_width = 20
        filled = int(bar_width * ratio)
        bar = "█" * filled + "░" * (bar_width - filled)
        lines.append(f"  · 【4DX计分板】周累计：{weekly_dw}h/{weekly_target}h {bar} {ratio:.0%}")
    # 冲刺任务提醒
    if sprint_tasks:
        lines.append(f"  · 🔥 冲刺任务{len(sprint_tasks)}个：{'、'.join(t['title'][:20] for t in sprint_tasks[:3])}")
    # 🆕 环境隔离三件套（替换原来的"别刷手机"一句话）
    lines.append("  · 🔒 【环境隔离检查】")
    lines.append("    信息层：飞书/微信通知已关？☐")
    lines.append("    空间层：耳机戴上/门关上/手机放别处？☐")
    lines.append("    时间层：接下来90分钟不可打断？☐")
    if dw_minutes < 180:
        lines.append("  · ⚡ 今日深度不足3h，下午完整段可补深度")
    lines.append("")

    # 🆕 ART注意力恢复建议
    art = schedule.get("art_recovery", {})
    if art.get("suggestions"):
        lines.append("🌿 【注意力恢复建议】")
        for s in art["suggestions"]:
            lines.append(f"  · {s}")
        lines.append("")

    # 🆕 习惯追踪模块
    habits = schedule.get("habits", [])
    if habits:
        lines.append("🏋️ 【今日习惯打卡】")
        for h in habits:
            fire = "🔥" * min(h["streak"] // 7, 3)
            identity_tag = f"（{h['identity']}）" if h["identity"] else ""
            # 新习惯(连续≤3)附两分钟规则提示
            two_min_tip = " → 先做2分钟版本" if h["streak"] <= 3 else ""
            lines.append(f"  · 🔲 {h['name']}{identity_tag} - 已连续{h['streak']}天{fire}{two_min_tip}")
        lines.append("")

    lines.append("╚══════════════════════════════════════╝")
    return "\n".join(lines)


# ============ 飞书操作 ============

def create_feishu_tasks(tasks, target_date=None, dry_run=False):
    """为今日任务创建飞书任务"""
    if target_date is None:
        target_date = date.today().strftime("%Y/%m/%d")

    created = []
    for t in tasks:
        # 截止时间：当天23:59:59的毫秒时间戳
        dt = datetime.strptime(target_date, "%Y/%m/%d")
        due_ms = str(int(dt.timestamp() * 1000 + 86399000))

        task_data = {
            "summary": t["title"],
            "description": f"预估耗时：{t['est_time']}分钟 | 精力消耗：{t['energy']}",
            "due": {"timestamp": due_ms, "is_all_day": True},
        }

        if dry_run:
            created.append({"title": t["title"], "dry_run": True})
            continue

        json_str = json.dumps(task_data, ensure_ascii=False)
        # 使用 @file 方式避免 shell 引号冲突
        tmp_name = f"_task_data_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        args = [
            "task", "tasks", "create",
            "--data", f"@{tmp_name}",
            "--as", "user",
        ]
        result = _run_lark(args)
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        if result.returncode == 0:
            try:
                resp = json.loads(result.stdout)
                task_id = resp.get("data", {}).get("task", {}).get("guid", "")
                created.append({"title": t["title"], "task_id": task_id, "ok": True})
            except json.JSONDecodeError:
                created.append({"title": t["title"], "ok": False, "error": result.stdout})
        else:
            created.append({"title": t["title"], "ok": False, "error": result.stderr})

    return created


def send_feishu_message(text, dry_run=False):
    """通过飞书发送消息"""
    if dry_run:
        print(f"[DRY-RUN] 将要发送消息到用户 {USER_OPEN_ID}")
        print(text)
        return {"ok": True, "dry_run": True}

    # 使用 markdown 格式发送
    result = _run_lark([
        "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--markdown", text,
        "--as", "user",
    ])

    if result.returncode == 0:
        return {"ok": True, "output": result.stdout}
    else:
        return {"ok": False, "error": result.stderr}


# ============ 主入口 ============

def main():
    dry_run = "--dry-run" in sys.argv
    target_date = None

    for arg in sys.argv[1:]:
        if arg.startswith("--date="):
            target_date = arg.split("=", 1)[1]
        elif arg.startswith("--date"):
            target_date = sys.argv[sys.argv.index(arg) + 1]

    if target_date:
        target_date = parse_date_str(target_date)

    run_analytics = "--analytics" in sys.argv

    if not dry_run:
        print(f"📅 排程日期：{target_date or date.today().strftime('%Y/%m/%d')}")

    # 1. 读取今日任务
    tasks = get_today_tasks(target_date)
    if not tasks:
        msg = "🎉 今天没有待办任务，可以休息或自由安排！"
        print(msg)
        if not dry_run:
            send_feishu_message(msg)
        return

    print(f"📊 读取到 {len(tasks)} 条任务")

    # 2. 读取科目基线
    baselines = get_subject_baselines()
    print(f"📊 读取到 {len(baselines)} 个科目基线")

    # 2.5 Body OS 能量策略调整
    energy_context = load_energy_context(target_date)
    if energy_context:
        body_result = adjust_tasks_for_energy_policy(tasks, energy_context, dry_run=dry_run)
        if body_result["overflow"]:
            ov_text = "、".join(t["title"][:20] for t in body_result["overflow"][:5])
            print(f"🧠 Body OS ({body_result['control_level']}级)：{len(body_result['overflow'])}个高精力任务溢出 — {ov_text}")
            if len(body_result["overflow"]) > 5:
                print(f"   ...还有 {len(body_result['overflow']) - 5} 个")
        # 用调整后的任务列表（overflow 已移除）生产排程
        tasks = body_result["tasks"]

    # 3. 生成排程
    schedule = generate_schedule(tasks, baselines, target_date, dry_run)

    # 3.5 深度记录自动预填（计划值写入Base，无手动记录时生效）
    auto_fill_deep_work_record(schedule, target_date, dry_run)

    # 4. 格式化推送文本（v2.0 全模块）
    push_text = format_schedule_v2(schedule)
    print("\n" + "=" * 50)
    print(push_text)
    print("=" * 50 + "\n")

    # 5. 创建飞书任务
    if dry_run:
        print("[DRY-RUN] 跳过任务创建和消息发送")
        return

    # 获取时间轴中的所有任务
    assigned_tasks = []
    for slot in schedule["timeline"]:
        assigned_tasks.extend(slot["tasks"])

    if assigned_tasks:
        print(f"📋 正在创建 {len(assigned_tasks)} 个飞书任务...")
        task_results = create_feishu_tasks(assigned_tasks, target_date)
        success = sum(1 for r in task_results if r.get("ok"))
        print(f"✅ 成功创建 {success}/{len(task_results)} 个任务")

    # 6. 同步到飞书日历
    try:
        from calendar_sync import sync_schedule_to_calendar
        print(f"📅 正在同步 {len(assigned_tasks)} 个任务到日历...")
        cal_result = sync_schedule_to_calendar(schedule, target_date)
        if cal_result.get("conflicts"):
            conflict_lines = ["", "⚠️ 【日历冲突】"]
            for ci in cal_result["conflicts"]:
                conflict_lines.append(f"  · {ci['slot']}（{ci['time']}）")
                for ce in ci["conflicting_events"][:2]:
                    conflict_lines.append(f"    与「{ce.get('summary', '?')}」冲突")
            conflict_lines.append("  💡 可通过 #排程到日历 重新安排冲突时段")
            push_text += "\n" + "\n".join(conflict_lines)
            print(f"⚠️ 检测到 {len(cal_result['conflicts'])} 个日历冲突")
        if cal_result.get("created", 0) > 0:
            print(f"✅ 已同步 {cal_result['created']} 个时段到日历")
    except ImportError:
        print("  [SKIP] calendar_sync 模块未安装")
    except Exception as e:
        print(f"  [WARN] 日历同步异常：{e}")

    # 7. 发送飞书消息
    print("📨 正在推送飞书消息...")
    msg_result = send_feishu_message(push_text)
    if msg_result.get("ok"):
        print("✅ 消息已推送")
    else:
        print(f"❌ 推送失败：{msg_result.get('error')}")

    # 8. 分析引擎（可选 — --analytics 标记）
    if run_analytics and not dry_run:
        try:
            print()
            print("=" * 40)
            print("📊 触发分析引擎...")
            from analytics_engine import AnalyticsEngine
            engine = AnalyticsEngine()
            report = engine.run_full_analysis(days_back=14)
            print()
            print("📋 报告摘要:")
            print(engine.summary_text(report))
        except ImportError:
            print("  [SKIP] analytics_engine 模块未安装")
        except Exception as e:
            print(f"  [WARN] 分析引擎异常：{e}")


if __name__ == "__main__":
    main()
