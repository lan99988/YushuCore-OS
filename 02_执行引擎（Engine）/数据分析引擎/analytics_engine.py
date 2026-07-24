#!/usr/bin/env python3
"""
分析引擎 — 个人混合管理系统的数据分析层
========================================
从飞书 Base 读取数据，计算分析指标，持久化快照，结果供仪表盘可视化。

角色定位：
  飞书 Base 是「数据中枢」和「可视化前端」，
  本引擎是「分析后端」—— 不新增外部依赖，零服务部署。

数据流：
  daily_scheduler.py ──(import)──→ analytics_engine.py
                                           │
       ┌───────────────────────────────────┤
       ▼                                   ▼
  读 Base 数据                      写结果回 Base
  (科目基线 + 执行记录                (分析结果表 /
    + 深度工作 + 排程日志)              仪表盘字段更新)

关键指标：
  · 科目燃尽（剩余内容 vs 剩余天数）
  · 任务完成率趋势（滚动窗口）
  · 时间投入分布（科目 / 时段 / 精力等级）
  · 深度工作统计（累计时长 / 趋势 / 心流分布）
  · 异常检测（中断日 / 大幅偏离 / 失衡警报）

用法：
  from analytics_engine import AnalyticsEngine

  engine = AnalyticsEngine()
  report = engine.run_full_analysis()
  print(report.summary())

  # 独立运行
  python analytics_engine.py                  # 完整分析 + 写 Base
  python analytics_engine.py --no-write       # 只打印不写
  python analytics_engine.py --dry-run        # 同 --no-write
  python analytics_engine.py --weekly         # 周报模式
"""

import json
import os
import sys
import sqlite3
import subprocess
import uuid
import re
import math
from datetime import datetime, date, timedelta
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional


# =============================================================================
# 配置
# =============================================================================

BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
TABLES = {
    "执行库": "tblNQCB4pn6Rso4a",
    "科目进度基线": "tblQnjCO03WjQ7GC",
    "深度工作追踪表": "tblmAz37er4CEbL0",
    "灵感库": "tblx1ZaQGwXvoJhj",
    "Bug库": "tblPpPputYMACtQ5",
}

LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\.bin\lark-cli.cmd"

# 本地快照数据库
SNAPSHOT_DB = os.path.join(os.path.dirname(__file__), "runtime", "_analytics.db")

# 分析窗口默认值
DEFAULT_DAYS_BACK = 30
WEEKLY_WINDOW = 7
ROLLING_WINDOW = 7
BURNDOWN_WINDOW = 60


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class SubjectStatus:
    """科目状态快照"""
    subject: str
    completion_rate: float        # 当前完成率 (0~100)
    daily_hours_planned: float    # 计划每日投入
    exam_date: str                # 考试日期
    days_remaining: int           # 剩余天数
    remaining_pct: float          # 剩余内容比例 (100 - completion_rate)
    daily_rate_needed: float      # 每天需要赶的进度百分比
    gap_status: str               # "领先" / "正常" / "落后" / "危险"


@dataclass
class CompletionRecord:
    """单日完成记录"""
    date: str                     # yyyy/MM/dd
    total: int                    # 当日总任务数
    completed: int                # 当日完成数
    completion_rate: float        # 完成率
    planned_minutes: float        # 计划总时长
    subjects: dict                # {科目: {total, completed}}


@dataclass
class DeepWorkRecord:
    """深度工作单日记录"""
    date: str
    deep_minutes: float
    shallow_minutes: float
    shallow_ratio: float
    flow_state: str
    distractions: int
    first_scoop: bool


@dataclass
class AnalysisReport:
    """完整分析报告"""
    generated_at: str = ""
    date_span: str = ""

    # 科目分析
    subjects: list = field(default_factory=list)

    # 燃尽数据 (每天一条)
    burndown: list = field(default_factory=list)

    # 任务完成趋势 (滚动窗口)
    completion_trend: dict = field(default_factory=dict)

    # 时间分布
    time_distribution: dict = field(default_factory=dict)

    # 深度工作
    deep_work: dict = field(default_factory=dict)

    # 异常警报
    anomalies: list = field(default_factory=list)

    # 一句话建议
    suggestions: list = field(default_factory=list)


# =============================================================================
# 工具函数
# =============================================================================

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

    try:
        full_args = [LARK_CLI] + args_list
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


def parse_date(s):
    """解析日期，统一为 yyyy/MM/dd"""
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(s))
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    return ""


def days_diff(d1, d2=None):
    """计算两个日期之间的天数差"""
    def to_date(s):
        p = parse_date(s)
        if not p:
            return None
        parts = p.split("/")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    a = to_date(d1)
    b = to_date(d2) if d2 else date.today()
    if not a:
        return 999
    return (a - b).days


def safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(v, default=0):
    try:
        return int(float(v)) if v else default
    except (ValueError, TypeError):
        return default


# =============================================================================
# 分析引擎
# =============================================================================

class AnalyticsEngine:
    """分析引擎 — 从飞书 Base 读取数据，计算分析指标"""

    def __init__(self, base_token=None, tables=None):
        self.base_token = base_token or BASE_TOKEN
        self.tables = tables or TABLES
        self._db_initialized = False

    # ------------------------------------------------------------------
    # 数据读取层
    # ------------------------------------------------------------------

    def fetch_subject_baselines(self) -> dict:
        """
        读取科目进度基线表。
        返回: { "数学二": { total_goal, completion_rate, daily_hours, exam_date, countdown }, ... }
        """
        result = _lark_json([
            "base", "+record-list",
            "--base-token", self.base_token,
            "--table-id", self.tables["科目进度基线"],
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
                "completion_rate": safe_float(_get("当前完成率", 0)),
                "daily_hours": safe_float(_get("平均每天应投入小时数", 0)),
                "exam_date": _get("考试日期", ""),
                "countdown": safe_int(_get("倒计时")),
            }
        return baselines

    def fetch_tasks(self, status_filter=None, days_back=None) -> list:
        """
        读取执行库任务记录。
        status_filter: 按状态过滤，默认全量
        days_back: 只取最近 N 天的任务
        返回: [{标题, 所属项目, 轻重缓急, 状态, 截止日期, 科目类别, 精力消耗等级, 预估耗时, 是否为今日硬骨头, 创建时间, ...}]
        """
        result = _lark_json([
            "base", "+record-list",
            "--base-token", self.base_token,
            "--table-id", self.tables["执行库"],
            "--as", "user",
            "--limit", "200",
            "--format", "json",
        ])
        if not result.get("ok"):
            return []

        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        tasks = []
        now = date.today()

        for row in data_array:
            fields = dict(zip(field_names, row))

            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v

            task = {
                "title": _get("标题", ""),
                "project": _get("所属项目", ""),
                "priority": _get("轻重缓急", ""),
                "status": _get("状态", "待收集"),
                "deadline": parse_date(_get("截止日期", "")),
                "subject": _get("科目类别", ""),
                "energy": _get("精力消耗等级", ""),
                "est_time": safe_int(_get("预估耗时", 0)),
                "is_tough": bool(_get("是否为今日硬骨头", False)),
                "created_at": parse_date(_get("创建时间", "")),
                "modified_at": parse_date(_get("最后修改时间", "")),
            }

            # 过滤
            if status_filter and task["status"] not in status_filter:
                continue
            if days_back:
                task_date = parse_date(task.get("created_at") or task.get("modified_at"))
                if task_date:
                    d = days_diff(now.isoformat().replace("-", "/"), task_date.replace("-", "/").replace("-", "/"))
                    if abs(d) > days_back:
                        continue

            tasks.append(task)

        return tasks

    def fetch_deep_work_records(self, days_back=None) -> list:
        """
        读取深度工作追踪表。
        返回: [{日期, 当日深度工作时长(min), 浅层时长(min), 当日浮浅工作占比, 最高心流状态, 干扰次数, 第一勺完成}]
        """
        result = _lark_json([
            "base", "+record-list",
            "--base-token", self.base_token,
            "--table-id", self.tables["深度工作追踪表"],
            "--as", "user",
            "--limit", "100",
            "--format", "json",
        ])
        if not result.get("ok"):
            return []

        d = result.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        records = []
        for row in data_array:
            fields = dict(zip(field_names, row))

            def _get(fn, default=None):
                v = fields.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v

            rec_date = parse_date(_get("日期", ""))
            if not rec_date:
                continue

            if days_back:
                d = days_diff(date.today().isoformat().replace("-", "/"), rec_date)
                if abs(d) > days_back:
                    continue

            records.append({
                "date": rec_date,
                "deep_minutes": safe_int(_get("当日深度工作时长(min)", 0)),
                "shallow_minutes": safe_int(_get("浅层时长(min)", 0)),
                "shallow_ratio": safe_float(_get("当日浮浅工作占比", 0)),
                "flow_state": _get("最高心流状态", "无"),
                "distractions": safe_int(_get("干扰次数", 0)),
                "first_scoop": bool(_get("第一勺完成", False)),
            })
        return records

    # ------------------------------------------------------------------
    # 分析计算层
    # ------------------------------------------------------------------

    def compute_subject_analysis(self, baselines: dict) -> list:
        """
        科目进度分析 — 当前完成状态 + 赶进度的每日速率。
        返回 [SubjectStatus, ...] 列表。
        """
        results = []
        for subject, bl in baselines.items():
            rate = safe_float(bl.get("completion_rate", 0))
            daily_hours = safe_float(bl.get("daily_hours", 0))
            exam_date = bl.get("exam_date", "")

            remaining = max(0, 100.0 - rate)
            days_left = days_diff(exam_date)

            # 每天需要赶的进度（占剩余内容的百分比）
            if days_left > 0 and remaining > 0:
                daily_needed = remaining / days_left
            else:
                daily_needed = 0

            # 状态判断
            rate_progress = rate / max(days_left, 1) * 100 if days_left > 0 else 0
            expected_progress = 100.0 / max(days_left + (days_diff(exam_date, date.today().isoformat().replace("-", "/")) - days_left), 1) * 100

            ratio = (rate / max(days_left, 1)) / (100.0 / max((days_left + 180), 1)) if days_left > 0 else 0
            if ratio >= 1.2:
                gap = "领先"
            elif ratio >= 0.8:
                gap = "正常"
            elif ratio >= 0.4:
                gap = "落后"
            else:
                gap = "危险"

            results.append(SubjectStatus(
                subject=subject,
                completion_rate=rate,
                daily_hours_planned=daily_hours,
                exam_date=exam_date,
                days_remaining=days_left,
                remaining_pct=remaining,
                daily_rate_needed=round(daily_needed, 2),
                gap_status=gap,
            ))
        return results

    def compute_burndown(self, baselines: dict, days_back=BURNDOWN_WINDOW) -> list:
        """
        燃尽数据 — 对每科生成预期完成曲线 vs 当前完成率。
        返回 [{date, subject, target, actual}]，用于折线图。
        """
        today = date.today()
        burndown = []

        for subject, bl in baselines.items():
            rate = safe_float(bl.get("completion_rate", 0))
            exam_date_str = bl.get("exam_date", "")
            exam = days_diff(exam_date_str)

            if exam <= 0:
                continue

            # 从今天到考试日，按天生成目标线
            # 目标线：从当前完成率线性延伸到 100%
            # 实际线：只有当前一个点，后续通过快照积累

            for i in range(0, min(days_back, exam + 1), 5):  # 5天间隔，减少数据点
                day = today + timedelta(days=i)
                day_str = day.strftime("%Y/%m/%d")
                # 目标完成率 = 起点 + (剩余进度 * 已过时间占比)
                remaining = 100.0 - rate
                elapsed_ratio = i / max(exam, 1)
                target = rate + (remaining * elapsed_ratio)

                burndown.append({
                    "date": day_str,
                    "subject": subject,
                    "target": round(min(target, 100), 1),
                    "actual": rate if i == 0 else None,  # 只有第一天有实际值
                })

        return burndown

    def compute_completion_trend(self, tasks: list, window=ROLLING_WINDOW) -> dict:
        """
        任务完成趋势分析。
        按日期聚合完成率，计算滚动均值。
        返回:
          {
            "daily": [{date, total, completed, rate}, ...],
            "rolling_avg": float,      # 滚动窗口平均完成率
            "total_in_window": int,    # 窗口内总任务数
            "completed_in_window": int, # 窗口内已完成数
            "top_subjects": [{subject, count}],  # 窗口内完成最多的科目
          }
        """
        if not tasks:
            return {"daily": [], "rolling_avg": 0, "total_in_window": 0,
                    "completed_in_window": 0, "top_subjects": []}

        # 按日期聚合
        daily = defaultdict(lambda: {"total": 0, "completed": 0, "subjects": defaultdict(lambda: {"total": 0, "completed": 0})})

        for t in tasks:
            mod_date = t.get("modified_at") or t.get("created_at") or ""
            if not mod_date:
                continue
            d = daily[mod_date]
            d["total"] += 1
            if t.get("status") == "已完成":
                d["completed"] += 1
            subj = t.get("subject") or "未分类"
            d["subjects"][subj]["total"] += 1
            if t.get("status") == "已完成":
                d["subjects"][subj]["completed"] += 1

        # 排序并限制窗口
        sorted_dates = sorted(daily.keys())[-window:]
        daily_list = []
        for dt in sorted_dates:
            info = daily[dt]
            rate = info["completed"] / max(info["total"], 1) * 100
            daily_list.append({
                "date": dt,
                "total": info["total"],
                "completed": info["completed"],
                "rate": round(rate, 1),
            })

        total = sum(d["total"] for d in daily_list)
        completed = sum(d["completed"] for d in daily_list)

        # 统计科目
        subject_count = defaultdict(int)
        for dt in sorted_dates:
            for subj, sinfo in daily[dt]["subjects"].items():
                subject_count[subj] += sinfo["completed"]
        top_subjects = sorted(subject_count.items(), key=lambda x: -x[1])[:5]
        top_subjects = [{"subject": s, "count": c} for s, c in top_subjects]

        return {
            "daily": daily_list,
            "rolling_avg": round(completed / max(total, 1) * 100, 1) if total > 0 else 0,
            "total_in_window": total,
            "completed_in_window": completed,
            "top_subjects": top_subjects,
        }

    def compute_time_distribution(self, tasks: list) -> dict:
        """
        时间投入分布分析。
        返回:
          {
            "by_subject": [{subject, total_minutes, task_count}, ...],
            "by_energy":  [{level, total_minutes, task_count}, ...],
            "by_priority": [{priority, total_minutes, task_count}, ...],
            "total_estimated_minutes": int,
          }
        """
        if not tasks:
            return {"by_subject": [], "by_energy": [],
                    "by_priority": [], "total_estimated_minutes": 0}

        # 只分析有预估时间的任务
        valid = [t for t in tasks if t.get("est_time", 0) > 0]

        by_subject = defaultdict(lambda: {"total_minutes": 0, "count": 0})
        by_energy = defaultdict(lambda: {"total_minutes": 0, "count": 0})
        by_priority = defaultdict(lambda: {"total_minutes": 0, "count": 0})

        for t in valid:
            est = t["est_time"]
            subj = t.get("subject") or "未分类"
            energy = t.get("energy") or "未指定"
            priority = t.get("priority") or "未指定"

            by_subject[subj]["total_minutes"] += est
            by_subject[subj]["count"] += 1
            by_energy[energy]["total_minutes"] += est
            by_energy[energy]["count"] += 1
            by_priority[priority]["total_minutes"] += est
            by_priority[priority]["count"] += 1

        def _sort(d):
            return sorted(
                [{"name": k, "total_minutes": v["total_minutes"], "task_count": v["count"]}
                 for k, v in d.items()],
                key=lambda x: -x["total_minutes"]
            )

        return {
            "by_subject": _sort(by_subject),
            "by_energy": _sort(by_energy),
            "by_priority": _sort(by_priority),
            "total_estimated_minutes": sum(t["est_time"] for t in valid),
        }

    def compute_deep_work_stats(self, records: list, window=WEEKLY_WINDOW) -> dict:
        """
        深度工作统计。
        返回:
          {
            "weekly_total_hours": float,
            "daily_avg_minutes": float,
            "trend": [{date, deep_minutes, shallow_ratio}, ...],
            "flow_distribution": [{state, count}, ...],
            "distraction_avg": float,
            "first_scoop_rate": float,
          }
        """
        if not records:
            return {"weekly_total_hours": 0, "daily_avg_minutes": 0,
                    "trend": [], "flow_distribution": [],
                    "distraction_avg": 0, "first_scoop_rate": 0}

        recent = sorted(records, key=lambda r: r["date"])[-window:]

        weekly_hours = sum(r["deep_minutes"] for r in recent) / 60.0
        daily_avg = sum(r["deep_minutes"] for r in recent) / max(len(recent), 1)

        trend = [{"date": r["date"], "deep_hours": round(r["deep_minutes"] / 60, 2),
                   "shallow_ratio": r["shallow_ratio"]} for r in recent]

        flow_count = defaultdict(int)
        for r in recent:
            flow_count[r["flow_state"]] += 1
        flow_dist = [{"state": s, "count": c} for s, c in sorted(flow_count.items(), key=lambda x: -x[1])]

        distraction_avg = sum(r["distractions"] for r in recent) / max(len(recent), 1)
        first_scoop_count = sum(1 for r in recent if r["first_scoop"])
        first_scoop_rate = first_scoop_count / max(len(recent), 1) * 100

        return {
            "weekly_total_hours": round(weekly_hours, 1),
            "daily_avg_minutes": round(daily_avg, 0),
            "trend": trend,
            "flow_distribution": flow_dist,
            "distraction_avg": round(distraction_avg, 1),
            "first_scoop_rate": round(first_scoop_rate, 1),
        }

    def detect_anomalies(self, deep_records: list, subject_analysis: list) -> list:
        """
        异常检测。
        返回 [{type, severity, message, date}]
        """
        anomalies = []

        # 1. 中断日检测：连续3天以上无深度工作记录
        if deep_records:
            sorted_records = sorted(deep_records, key=lambda r: r["date"], reverse=True)
            gap_days = 0
            today_str = date.today().strftime("%Y/%m/%d")
            # 检查最近连续无记录天数
            check_date = date.today()
            record_dates = {r["date"] for r in deep_records}
            while check_date.weekday() < 5:  # 只检查工作日
                ds = check_date.strftime("%Y/%m/%d")
                if ds not in record_dates:
                    gap_days += 1
                else:
                    break
                check_date -= timedelta(days=1)

            if gap_days >= 3:
                anomalies.append({
                    "type": "中断",
                    "severity": "高",
                    "message": f"连续 {gap_days} 天无深度工作记录",
                    "date": today_str,
                })

        # 2. 科目失衡检测
        if subject_analysis:
            dangerous = [s for s in subject_analysis if s.gap_status == "危险"]
            behind = [s for s in subject_analysis if s.gap_status == "落后"]
            if dangerous:
                subjects_str = "、".join(s.subject for s in dangerous)
                anomalies.append({
                    "type": "科目落后",
                    "severity": "严重",
                    "message": f"科目 {subjects_str} 进度严重落后，需加大投入",
                    "date": date.today().strftime("%Y/%m/%d"),
                })
            if behind:
                subjects_str = "、".join(s.subject for s in behind)
                anomalies.append({
                    "type": "科目滞后",
                    "severity": "中",
                    "message": f"科目 {subjects_str} 进度偏慢，建议调整优先级",
                    "date": date.today().strftime("%Y/%m/%d"),
                })

        # 3. 浅层工作占比异常
        if deep_records:
            recent_deep = sorted(deep_records, key=lambda r: r["date"])[-7:]
            high_shallow = [r for r in recent_deep if r["shallow_ratio"] > 0.5]
            if len(high_shallow) >= 3:
                anomalies.append({
                    "type": "浮浅过载",
                    "severity": "中",
                    "message": f"近7天有 {len(high_shallow)} 天浮浅工作占比超过50%，注意深度保护",
                    "date": date.today().strftime("%Y/%m/%d"),
                })

        return anomalies

    def generate_suggestions(self, subject_analysis: list, completion_trend: dict,
                              deep_work: dict, anomalies: list) -> list:
        """
        生成一句话建议。
        """
        suggestions = []

        # 科目建议
        for s in subject_analysis:
            if s.gap_status == "危险":
                suggestions.append(
                    f"🔴 {s.subject}：剩余 {s.days_remaining} 天需完成 {s.remaining_pct:.0f}%，"
                    f"每天需赶 {s.daily_rate_needed:.1f}%，建议加大投入")
            elif s.gap_status == "落后":
                suggestions.append(
                    f"🟡 {s.subject}：进度偏慢，每天需赶 {s.daily_rate_needed:.1f}%，"
                    f"建议当前每日 {s.daily_hours_planned}h → {s.daily_hours_planned + 0.5}h")

        # 完成率建议
        ra = completion_trend.get("rolling_avg", 0)
        if ra < 50:
            suggestions.append(f"🟡 任务完成率仅 {ra:.0f}%，建议精简每日任务量，聚焦核心事件")
        elif ra >= 80:
            suggestions.append(f"🟢 任务完成率 {ra:.0f}%，执行状态良好")

        # 深度工作建议
        dw = deep_work.get("weekly_total_hours", 0)
        if dw < 15:
            suggestions.append(f"🟡 本周深度工作仅 {dw}h，建议至少达到 25h 目标")
        elif dw >= 25:
            suggestions.append(f"🟢 本周深度工作 {dw}h，达标！")

        # 异常
        for a in anomalies:
            if a["severity"] in ("高", "严重"):
                suggestions.append(f"🔴 {a['message']}")

        return suggestions

    # ------------------------------------------------------------------
    # 持久化层（本地 SQLite 快照）
    # ------------------------------------------------------------------

    def _init_db(self):
        """初始化本地快照数据库"""
        if self._db_initialized:
            return
        os.makedirs(os.path.dirname(SNAPSHOT_DB), exist_ok=True)
        conn = sqlite3.connect(SNAPSHOT_DB)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                date TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subject_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                subject TEXT NOT NULL,
                completion_rate REAL,
                days_remaining INTEGER,
                daily_hours REAL,
                UNIQUE(date, subject)
            );
        """)
        conn.commit()
        conn.close()
        self._db_initialized = True

    def save_snapshot(self, report: AnalysisReport):
        """
        保存当日分析快照到本地 SQLite。
        """
        self._init_db()
        today = date.today().strftime("%Y/%m/%d")
        conn = sqlite3.connect(SNAPSHOT_DB)

        # 完整报告快照（JSON）
        report_dict = {
            "generated_at": report.generated_at,
            "date_span": report.date_span,
            "burndown": report.burndown,
            "completion_trend": report.completion_trend,
            "time_distribution": report.time_distribution,
            "deep_work": report.deep_work,
            "anomalies": report.anomalies,
            "suggestions": report.suggestions,
        }
        conn.execute(
            "INSERT OR REPLACE INTO daily_snapshots (date, data) VALUES (?, ?)",
            (today, json.dumps(report_dict, ensure_ascii=False))
        )

        # 科目快照（结构化，便于 SQL 查询趋势）
        for s in report.subjects:
            conn.execute(
                "INSERT OR REPLACE INTO subject_snapshots "
                "(date, subject, completion_rate, days_remaining, daily_hours) "
                "VALUES (?, ?, ?, ?, ?)",
                (today, s.subject, s.completion_rate,
                 s.days_remaining, s.daily_hours_planned)
            )

        conn.commit()
        conn.close()

    def load_snapshot(self, target_date=None):
        """
        读取指定日期的快照。
        target_date: 默认今天
        返回 dict 或 None
        """
        self._init_db()
        if not target_date:
            target_date = date.today().strftime("%Y/%m/%d")
        conn = sqlite3.connect(SNAPSHOT_DB)
        cursor = conn.execute(
            "SELECT data FROM daily_snapshots WHERE date = ?", (target_date,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def load_trend(self, subject: str, days_back=30) -> list:
        """
        读取某科目历史快照趋势。
        返回 [{date, completion_rate}, ...]
        """
        self._init_db()
        conn = sqlite3.connect(SNAPSHOT_DB)
        cursor = conn.execute(
            "SELECT date, completion_rate FROM subject_snapshots "
            "WHERE subject = ? ORDER BY date DESC LIMIT ?",
            (subject, days_back)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"date": r[0], "completion_rate": r[1]} for r in rows]

    # ------------------------------------------------------------------
    # 写回飞书 Base
    # ------------------------------------------------------------------

    def write_analysis_to_base(self, report: AnalysisReport, table_id: str = None):
        """
        将分析摘要写回飞书 Base 指定表（用于仪表盘数据源）。
        默认写入 科目进度基线 的「分析摘要」字段。
        """
        # 暂实现为打印日志，后续可按需实现字段更新
        # 接口预留：table_id 可以是指定写回的目标表
        pass

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def run_full_analysis(self, days_back=DEFAULT_DAYS_BACK) -> AnalysisReport:
        """
        全量分析 — 读取所有数据源，计算全部指标，返回 AnalysisReport。
        """
        report = AnalysisReport()
        report.generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
        today = date.today()
        start = today - timedelta(days=days_back)
        report.date_span = f"{start.strftime('%Y/%m/%d')} – {today.strftime('%Y/%m/%d')}"

        print(f"📊 分析引擎启动 — 窗口 {days_back} 天")
        print()

        # 1. 科目进度
        print("读取科目进度基线...")
        baselines = self.fetch_subject_baselines()
        report.subjects = self.compute_subject_analysis(baselines)
        report.burndown = self.compute_burndown(baselines)

        print(f"  → {len(report.subjects)} 个科目")
        for s in report.subjects:
            icon = {"领先": "🟢", "正常": "🔵", "落后": "🟡", "危险": "🔴"}.get(s.gap_status, "⚪")
            print(f"  {icon} {s.subject}: {s.completion_rate:.0f}% | "
                  f"剩余{s.days_remaining}天 | "
                  f"每日需{s.daily_rate_needed:.1f}% | {s.gap_status}")
        print()

        # 2. 任务完成趋势
        print("读取执行库任务...")
        tasks = self.fetch_tasks(days_back=days_back)
        report.completion_trend = self.compute_completion_trend(tasks)
        ct = report.completion_trend
        print(f"  → 窗口内任务: {ct['total_in_window']} | "
              f"已完成: {ct['completed_in_window']} | "
              f"滚动完成率: {ct['rolling_avg']:.1f}%")
        print()

        # 3. 时间分布
        print("计算时间分布...")
        report.time_distribution = self.compute_time_distribution(tasks)
        td = report.time_distribution
        total_h = td["total_estimated_minutes"] / 60.0
        print(f"  → 预估总时长: {total_h:.1f}h")
        for item in td["by_subject"][:5]:
            print(f"  · {item['name']}: {item['total_minutes'] / 60:.1f}h ({item['task_count']}项)")
        print()

        # 4. 深度工作
        print("读取深度工作记录...")
        deep_records = self.fetch_deep_work_records(days_back=days_back)
        report.deep_work = self.compute_deep_work_stats(deep_records)
        dw = report.deep_work
        print(f"  → 周累计深度: {dw['weekly_total_hours']}h | "
              f"日均: {dw['daily_avg_minutes']:.0f}min | "
              f"干扰均值: {dw['distraction_avg']}/天 | "
              f"第一勺率: {dw['first_scoop_rate']:.0f}%")
        print()

        # 5. 异常检测
        print("异常检测...")
        report.anomalies = self.detect_anomalies(deep_records, report.subjects)
        if report.anomalies:
            for a in report.anomalies:
                icon = {"严重": "🚨", "高": "🔴", "中": "🟡"}.get(a["severity"], "⚪")
                print(f"  {icon} [{a['severity']}] {a['message']}")
        else:
            print("  ✅ 无异常")
        print()

        # 6. 建议生成
        report.suggestions = self.generate_suggestions(
            report.subjects, report.completion_trend, report.deep_work, report.anomalies)

        print("💡 建议:")
        for s in report.suggestions:
            print(f"  {s}")
        print()

        # 7. 持久化
        self.save_snapshot(report)
        print(f"💾 快照已保存 → {SNAPSHOT_DB}")

        return report

    def summary_text(self, report: AnalysisReport = None) -> str:
        """
        生成报告摘要文本（纯文本，适合推送消息）。
        """
        if not report:
            report = self.run_full_analysis()

        lines = []
        lines.append(f"📊 分析报告 — {report.date_span}")
        lines.append("")

        # 科目
        lines.append("【科目进度】")
        for s in report.subjects:
            icon = {"领先": "🟢", "正常": "🔵", "落后": "🟡", "危险": "🔴"}.get(s.gap_status, "⚪")
            lines.append(f"  {icon} {s.subject}: {s.completion_rate:.0f}% "
                         f"(剩{s.days_remaining}天, 每日需{s.daily_rate_needed:.1f}%)")
        lines.append("")

        # 完成率
        ct = report.completion_trend
        lines.append(f"【执行】完成率 {ct['rolling_avg']:.0f}% | "
                     f"{ct['completed_in_window']}/{ct['total_in_window']}")

        # 时间
        td = report.time_distribution
        top = td["by_subject"][:3]
        if top:
            parts = [f"{item['name']}:{item['total_minutes'] / 60:.0f}h" for item in top]
            lines.append(f"【时间】{'  '.join(parts)}")

        # 深度工作
        dw = report.deep_work
        lines.append(f"【深度】周{dw['weekly_total_hours']}h | "
                     f"日均{dw['daily_avg_minutes']:.0f}min | "
                     f"第一勺{dw['first_scoop_rate']:.0f}%")

        # 异常
        if report.anomalies:
            lines.append(f"【异常】{len(report.anomalies)}项")
            for a in report.anomalies[:3]:
                lines.append(f"  · {a['message']}")

        # 建议
        if report.suggestions:
            lines.append("")
            lines.append("💡 建议:")
            for s in report.suggestions[:4]:
                lines.append(f"  {s}")

        return "\n".join(lines)


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="分析引擎 — 个人混合管理系统")
    parser.add_argument("--no-write", action="store_true",
                        help="只打印结果，不写快照")
    parser.add_argument("--dry-run", action="store_true",
                        help="同 --no-write")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK,
                        help=f"分析窗口天数（默认 {DEFAULT_DAYS_BACK}）")
    parser.add_argument("--weekly", action="store_true",
                        help="周报模式（7天窗口 + 精简输出）")
    parser.add_argument("--summary", action="store_true",
                        help="只输出摘要文本（适合消息推送）")

    args = parser.parse_args()

    engine = AnalyticsEngine()
    days_back = 7 if args.weekly else args.days

    if args.summary or args.weekly:
        report = engine.run_full_analysis(days_back=days_back)
        if args.no_write or args.dry_run:
            pass  # run_full_analysis 已 save_snapshot
        text = engine.summary_text(report)
        print("\n" + "=" * 40)
        print(text)
    else:
        engine.run_full_analysis(days_back=days_back)

    sys.exit(0)


if __name__ == "__main__":
    main()
