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
}

# lark-cli 路径
LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\cli-connector-packages\lark-cli"

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
    # (时段名称, 开始, 结束, 精力等级, 备注)
    ("高效段①", "09:00", "10:30", "高", "高效学习"),
    ("休息",    "10:30", "10:45", None,   "恢复精力"),
    ("高效段②", "10:45", "12:15", "高", "高效学习"),
    ("午休",    "12:15", "14:00", None,   "午餐+休息"),
    ("完整段①", "14:00", "17:00", "中", "可支配完整时间"),
    ("休息",    "17:00", "17:15", None,   "短暂放松"),
    ("完整段②", "17:15", "18:45", "中", "可支配完整时间"),
    ("晚餐",    "18:45", "20:00", None,   "晚餐"),
    ("零散段",  "20:00", "22:00", "低", "零散时间"),
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

    cli_path = LARK_CLI.replace("\\", "/")
    cmd_parts = [f'"{cli_path}"'] + [f'"{a}"' for a in args_list]
    cmd_str = " ".join(cmd_parts)

    # 清理临时文件
    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

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

def load_energy_status():
    """读取精力状态记录"""
    if not os.path.exists(ENERGY_STATUS_FILE):
        return None
    try:
        with open(ENERGY_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 只取当天的记录
        today = date.today().isoformat()
        if data.get("date") == today:
            return data.get("status")
    except (json.JSONDecodeError, IOError):
        pass
    return None


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
    energy_status = load_energy_status()
    config = load_config()

    base_hours = float(config.get("今日可用时长", DEFAULT_DAILY_HOURS))
    energy_multiplier = float(config.get("精力系数", 1.0))
    if energy_status == "差":
        energy_multiplier = 0.8
    elif energy_status == "好":
        energy_multiplier = 1.2
    if "精力系数" in config:
        energy_multiplier = float(config["精力系数"])
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

    for name, start, end, energy, note in SLOT_LAYOUT:
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

    # v2.0 新增模块查询
    core_event = get_core_event(tasks)
    social_reminders = query_social_reminders()
    finance_summary = query_finance_summary()
    creation_progress = query_creation_progress()
    knowledge_stats = query_knowledge_stats()

    return {
        "date": target_date,
        "available_hours": round(available_hours, 1),
        "energy_status": energy_status or "正常",
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
    }


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
        note = slot.get("note", "")
        lines.append(f"{icon} {slot['slot']}（{slot['time']}）· {note}")
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

    # 🎯 核心事件
    core = schedule.get("core_event")
    if core:
        lines.append(f"🎯 【核心事件】今日必完成：{core['title']}")
        lines.append("   （完成它就值得了！）")
        lines.append("")

    # 时间轴
    for slot in schedule["timeline"]:
        icon = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(slot["energy"], "⚪")
        note = slot.get("note", "")
        lines.append(f"{icon} {slot['slot']}（{slot['time']}）· {note}")
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

    # 3. 生成排程
    schedule = generate_schedule(tasks, baselines, target_date, dry_run)

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

    # 6. 发送飞书消息
    print("📨 正在推送飞书消息...")
    msg_result = send_feishu_message(push_text)
    if msg_result.get("ok"):
        print("✅ 消息已推送")
    else:
        print(f"❌ 推送失败：{msg_result.get('error')}")


if __name__ == "__main__":
    main()
