"""
复盘 Handler（Step2-4-C-7）

职责：处理 #复盘 / #复盘深度 指令，拉取飞书记录并生成本地统计报告。

迁移来源：input_parser_old.py
- handle_review        (1094-1200)
- handle_deep_review   (1560-1673)
- router._call_review  (111-119) 中的二级分发（days 解析 + 「深度」判断）

原则（搬家不装修）：
- 三个函数 1:1 复刻，仅做 text→raw_text 命名变化与包内 import 调整。
- 旧 router 桥 _call_review 的「days 解析 + 深度判断」逻辑并入公开入口
  handle_review(raw_text, ...)，不再依赖 router 桥。
- 输出契约、统计字段、异常处理、dry_run 形参行为全部与旧实现逐字一致。
- 不抽公共统计函数、不合并 deep_review、不改字段/异常/输出格式。
"""

import re
import json
from datetime import datetime, timedelta

from ..config import BASE_TOKEN, TABLES
from ..lark_bridge import _run_lark_cli

# 深度工作追踪表（与旧 monolith 一致；deep_record 迁移时各自声明，保持不跨文件重构）
DEEP_WORK_TABLE_ID = "tblmAz37er4CEbL0"  # 深度工作追踪表


def _handle_review(days=7, dry_run=False):
    """处理 #复盘 指令：拉取过去N天的执行库记录，生成复盘报告

    Args:
        days: 回顾天数，默认7天
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 读取执行库
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["执行库"],
        "--as", "user",
        "--limit", "500",
        "--format", "json",
    ])

    if result.returncode != 0:
        return {"ok": False, "error": "读取执行库失败"}

    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        total_tasks = 0
        completed = 0
        by_project = {}
        by_category = {}
        by_priority = {}
        time_spent = 0

        for row in data_array:
            fields = dict(zip(field_names, row))
            status = fields.get("状态", "")

            # 检查创建时间是否在回顾期内
            created = fields.get("创建时间", "")
            if created:
                try:
                    created_dt = datetime.strptime(str(created)[:19], "%Y-%m-%dT%H:%M:%S")
                    if not (start_date <= created_dt <= end_date):
                        continue
                except ValueError:
                    continue

            total_tasks += 1
            project = fields.get("所属项目", "未知")
            cat = fields.get("科目类别", "")
            priority = fields.get("轻重缓急", "P3")
            est_time = fields.get("预估耗时", 0) or 0

            try:
                est_time = int(est_time)
            except (ValueError, TypeError):
                est_time = 0

            if status == "已完成":
                completed += 1
                time_spent += est_time

            by_project[project] = by_project.get(project, 0) + 1
            if cat:
                by_category[cat] = by_category.get(cat, 0) + 1
            by_priority[priority] = by_priority.get(priority, 0) + 1

        completion_rate = round(completed / total_tasks * 100, 1) if total_tasks > 0 else 0

        # 生成复盘报告
        report = []
        report.append(f"📊 【{days}天复盘报告】（{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')}）")
        report.append(f"")
        report.append(f"总任务：{total_tasks} | 完成：{completed} | 完成率：{completion_rate}%")
        report.append(f"总耗时：{time_spent} 分钟（{time_spent/60:.1f}h）")
        report.append(f"")
        report.append("按项目分布：")
        for proj, cnt in sorted(by_project.items(), key=lambda x: -x[1]):
            report.append(f"  · {proj}：{cnt} 项")
        report.append(f"")
        if by_category:
            report.append("按科目分布：")
            for cat, cnt in sorted(by_category.items(), key=lambda x: -x[1]):
                report.append(f"  · {cat}：{cnt} 项")
            report.append(f"")
        report.append("按优先级分布：")
        for pri, cnt in sorted(by_priority.items(), key=lambda x: -x[1]):
            report.append(f"  · {pri}：{cnt} 项")

        return {
            "ok": True,
            "type": "review",
            "message": "\n".join(report),
            "stats": {
                "total": total_tasks,
                "completed": completed,
                "completion_rate": completion_rate,
                "time_spent": time_spent,
                "by_project": by_project,
                "by_category": by_category,
                "by_priority": by_priority,
            }
        }
    except (json.JSONDecodeError, KeyError):
        return {"ok": False, "error": "解析执行库数据失败"}


def _handle_deep_review(days=7, dry_run=False):
    """处理 #复盘深度 指令：深度工作专项复盘"""
    # 读取深度工作追踪表
    try:
        args = [
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", DEEP_WORK_TABLE_ID,
            "--as", "user",
            "--limit", "100",
            "--format", "json",
        ]
        result = _run_lark_cli(args)
        if result.returncode != 0:
            return {"ok": True, "type": "deep_review", "message": "深度工作追踪表暂未创建，试试先 #深度记录"}

        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        records_in_range = []
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
                    dr_dt = datetime.strptime(str(dr)[:10], "%Y/%m/%d")
                    if start_date <= dr_dt <= end_date:
                        records_in_range.append(fields)
                except ValueError:
                    pass

        if not records_in_range:
            return {"ok": True, "type": "deep_review", "message": f"过去{days}天没有深度工作记录"}

        total_deep_minutes = 0
        total_distractions = 0
        flow_days = 0
        day_count = len(records_in_range)

        for rec in records_in_range:

            def _get(fn, default=None):
                v = rec.get(fn, default)
                if isinstance(v, list):
                    return v[0] if v else default
                return v

            dm = _get("当日深度工作时长(min)", 0) or 0
            total_deep_minutes += int(dm)
            dist = _get("干扰次数", 0) or 0
            total_distractions += int(dist)
            flow = _get("最高心流状态", "")
            if flow in ("高", "巅峰"):
                flow_days += 1

        avg_deep = round(total_deep_minutes / day_count / 60, 1) if day_count > 0 else 0
        avg_dist = round(total_distractions / day_count, 1) if day_count > 0 else 0

        report = []
        report.append(f"🔴 【深度工作复盘】（{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')}）")
        report.append(f"📊 记录天数：{day_count}")
        report.append(f"⏱ 总深度时长：{total_deep_minutes//60}h{total_deep_minutes%60}m")
        report.append(f"📈 日均深度：{avg_deep}h")
        report.append(f"🧠 心流高峰日：{flow_days}/{day_count}")
        report.append(f"🔔 日均干扰：{avg_dist}次")
        report.append(f"")
        report.append("💡 建议：")
        if avg_deep < 3:
            report.append("  · 日均深度 < 3h，尝试增加深度工作时段")
        if avg_dist > 3:
            report.append(f"  · 日均干扰 {avg_dist}次，检查干扰源并排除")
        if flow_days < day_count * 0.5:
            report.append("  · 心流率偏低，尝试罗斯福冲刺来进入状态")

        # 🆕 4DX第四原则：模式识别（P0-④）
        report.append(f"")
        report.append("🔍 【模式识别】请思考以下问题：")
        report.append(f"  1. 哪天深度时间最少？那天发生了什么？")
        report.append(f"  2. 是否在用「思维账户」掩盖「体能账户」的问题？")
        report.append(f"     （脑子还能转，但身体已经累了，硬撑导致效率低）")
        report.append(f"  3. 干扰主要来自哪个源？能否物理消除？")
        report.append(f"  4. 第一勺冰淇淋完成率？未完成的原因是什么？")

        # 🆕 职场资本评估（P1-⑧）
        report.append(f"")
        report.append("💼 【职场资本评估】本周")
        report.append(f"  · 积累资本：深度工作 {total_deep_minutes//60}h{total_deep_minutes%60}m（引领指标）")
        report.append(f"  · 技能提升：学会了什么新能力？")
        report.append(f"  · 可展示成果：产出了什么可被评价的东西？")
        report.append(f"  · 消耗项：哪些活动在浪费时间但不提升能力？")
        report.append(f"  · 判断：这周是 ↑增强 还是 ↓削弱？")

        return {
            "ok": True,
            "type": "deep_review",
            "message": "\n".join(report),
            "stats": {
                "days": day_count,
                "total_deep_minutes": total_deep_minutes,
                "avg_deep_hours": avg_deep,
                "flow_days": flow_days,
                "avg_distractions": avg_dist,
            }
        }
    except Exception as e:
        return {"ok": True, "type": "deep_review", "message": f"深度复盘临时不可用：{e}"}


def handle_review(raw_text, dry_run=False):
    """公开入口：复刻旧 router._call_review 的二级分发逻辑。

    - 解析 #复盘 后的天数（默认 7）
    - 文本含「深度」→ 深度工作复盘，否则普通复盘
    """
    days = 7
    m = re.search(r'#复盘\s+(\d+)', raw_text)
    if m:
        days = int(m.group(1))
    if "深度" in raw_text:
        return _handle_deep_review(days, dry_run=dry_run)
    return _handle_review(days, dry_run=dry_run)
