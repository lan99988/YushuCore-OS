#!/usr/bin/env python3
"""
深度工作周报生成器
==================
每周日21:00自动运行，读取深度工作追踪表，生成可视化周报并推送飞书。

用法：
    python weekly_deep_review.py              # 正常模式（推送飞书）
    python weekly_deep_review.py --dry-run    # 测试模式（不推送）
    python weekly_deep_review.py --days 14    # 自定义天数
"""

import json
import subprocess
import os
import sys
from datetime import datetime, date, timedelta

# ============ 配置 ============
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
DEEP_WORK_TABLE_ID = "tblmAz37er4CEbL0"
LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\.bin\lark-cli.cmd"
USER_OPEN_ID = "ou_adf2c637b6ddd79c0af429ad5da3a746"


def _run_lark(args_list, json_input=None):
    """运行 lark-cli 命令"""
    import uuid
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


def fetch_deep_work_records(days=7):
    """读取深度工作追踪表记录"""
    result = _lark_json([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", DEEP_WORK_TABLE_ID,
        "--as", "user",
        "--limit", "100",
        "--format", "json",
    ])

    if not result.get("ok"):
        return []

    d = result.get("data", {})
    field_names = d.get("fields", [])
    data_array = d.get("data", [])

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    records = []
    for row in data_array:
        fields = dict(zip(field_names, row))
        def _get(fn, default=None):
            v = fields.get(fn, default)
            if isinstance(v, list):
                return v[0] if v else default
            return v

        dr = _get("日期", "")
        if not dr:
            continue
        try:
            dr_dt = datetime.strptime(str(dr)[:10], "%Y/%m/%d")
            if start_date <= dr_dt <= end_date:
                records.append({
                    "date": str(dr)[:10],
                    "deep_minutes": int(_get("当日深度工作时长(min)", 0) or 0),
                    "shallow_pct": int(_get("当日浮浅工作占比", 0) or 0),
                    "shallow_minutes": int(_get("浅层时长(min)", 0) or 0),
                    "flow": _get("最高心流状态", "无"),
                    "distractions": int(_get("干扰次数", 0) or 0),
                    "sprints": int(_get("冲刺任务数", 0) or 0),
                    "recovery": _get("恢复活动", ""),
                    "first_scoop": _get("第一勺完成", False),
                    "note": _get("备注", ""),
                })
        except (ValueError, TypeError):
            continue

    records.sort(key=lambda r: r["date"])
    return records


def generate_weekly_report(records, days=7):
    """生成可视化周报文本"""
    if not records:
        return f"📊 过去{days}天没有深度工作记录。\n💡 试试用 `#深度记录 深度3h 心流高` 记录今天的表现！"

    day_count = len(records)
    total_deep = sum(r["deep_minutes"] for r in records)
    total_shallow = sum(r["shallow_minutes"] for r in records)
    total_distractions = sum(r["distractions"] for r in records)
    flow_high = sum(1 for r in records if r["flow"] in ("高", "巅峰"))
    first_scoop_done = sum(1 for r in records if r.get("first_scoop"))
    sprint_total = sum(r["sprints"] for r in records)

    avg_deep = round(total_deep / day_count / 60, 1) if day_count > 0 else 0
    avg_dist = round(total_distractions / day_count, 1) if day_count > 0 else 0
    weekly_target = 25.0
    weekly_ratio = min(1.0, total_deep / 60 / weekly_target) if weekly_target > 0 else 0

    lines = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append(f"║   📊 深度工作周报（{days}天）           ║")
    lines.append("╠══════════════════════════════════════╣")
    lines.append("")

    # 1. 4DX计分板
    lines.append("🎯 【4DX计分板】")
    bar_width = 25
    filled = int(bar_width * weekly_ratio)
    bar = "█" * filled + "░" * (bar_width - filled)
    lines.append(f"  周累计深度：{total_deep//60}h{total_deep%60}m / {weekly_target:.0f}h")
    lines.append(f"  {bar} {weekly_ratio:.0%}")
    lines.append("")

    # 2. 每日深度时长柱状图
    lines.append("📈 【每日深度时长】")
    max_deep = max((r["deep_minutes"] for r in records), default=60)
    for r in records:
        ratio = r["deep_minutes"] / max(max_deep, 1)
        bar_len = int(20 * ratio)
        bar = "▰" * bar_len + "▱" * (20 - bar_len)
        date_short = r["date"][5:]  # MM-DD
        lines.append(f"  {date_short} {bar} {r['deep_minutes']//60}h{r['deep_minutes']%60:02d}m")
    lines.append(f"  日均：{avg_deep}h")
    lines.append("")

    # 3. 浮浅工作占比趋势
    lines.append("📊 【浮浅工作占比】")
    for r in records:
        pct = r.get("shallow_pct", 0)
        if pct > 0:
            status = "✅" if pct <= 30 else "⚠️"
            date_short = r["date"][5:]
            lines.append(f"  {date_short} {pct}% {status}")
    lines.append("")

    # 4. 心流状态分布
    lines.append("🧠 【心流状态分布】")
    flow_counts = {}
    for r in records:
        flow_counts[r["flow"]] = flow_counts.get(r["flow"], 0) + 1
    for state in ["巅峰", "高", "中", "低", "无"]:
        count = flow_counts.get(state, 0)
        if count > 0:
            bar = "●" * count
            lines.append(f"  {state}：{bar} ({count}天)")
    lines.append("")

    # 5. 第一勺冰淇淋完成率
    lines.append("🍦 【第一勺冰淇淋完成率】")
    if day_count > 0:
        scoop_rate = first_scoop_done / day_count
        bar_w = 20
        filled_s = int(bar_w * scoop_rate)
        bar_s = "█" * filled_s + "░" * (bar_w - filled_s)
        lines.append(f"  {bar_s} {scoop_rate:.0%}（{first_scoop_done}/{day_count}天）")
    lines.append("")

    # 6. 干扰分析
    lines.append("🔔 【干扰分析】")
    lines.append(f"  总干扰次数：{total_distractions}")
    lines.append(f"  日均干扰：{avg_dist}次")
    if avg_dist > 3:
        lines.append(f"  ⚠️ 干扰偏高！主要来源是什么？能否物理消除？")
    lines.append("")

    # 7. 恢复活动记录
    recovery_records = [r for r in records if r.get("recovery")]
    if recovery_records:
        lines.append("🌿 【恢复活动记录】")
        for r in recovery_records:
            date_short = r["date"][5:]
            lines.append(f"  {date_short} {r['recovery']}")
        lines.append("")

    # 8. 模式识别（4DX第四原则）
    lines.append("🔍 【模式识别】请思考：")
    min_deep_day = min(records, key=lambda r: r["deep_minutes"]) if records else None
    if min_deep_day:
        lines.append(f"  · 深度最少的一天：{min_deep_day['date'][5:]}（{min_deep_day['deep_minutes']//60}h{min_deep_day['deep_minutes']%60}m）")
        lines.append(f"    那天发生了什么？")
    lines.append(f"  · 是否在用「思维账户」掩盖「体能账户」？")
    lines.append(f"  · 干扰主要来自哪个源？")
    lines.append(f"  · 第一勺完成率{first_scoop_done}/{day_count}，未完成的原因？")
    lines.append("")

    # 9. 职场资本评估
    lines.append("💼 【职场资本评估】")
    lines.append(f"  · 积累资本：深度工作 {total_deep//60}h{total_deep%60}m")
    lines.append(f"  · 技能提升：本周学会了什么新能力？")
    lines.append(f"  · 可展示成果：产出了什么可被评价的东西？")
    lines.append(f"  · 消耗项：哪些活动在浪费时间但不提升能力？")
    lines.append(f"  · 判断：这周是 ↑增强 还是 ↓削弱？")
    lines.append("")

    # 10. 下周建议
    lines.append("📋 【下周建议】")
    suggestions = []
    if avg_deep < 3:
        suggestions.append(f"  · 日均深度 {avg_deep}h < 3h，尝试增加深度时段")
    if avg_dist > 3:
        suggestions.append(f"  · 日均干扰 {avg_dist}次，需要环境隔离")
    if weekly_ratio < 0.5:
        suggestions.append(f"  · 周累计仅 {weekly_ratio:.0%}，离目标还有差距")
    if first_scoop_done / max(day_count, 1) < 0.7:
        suggestions.append(f"  · 第一勺完成率低，尝试每天第一件事就做")
    if flow_high < day_count * 0.3:
        suggestions.append(f"  · 心流率偏低，尝试罗斯福冲刺进入状态")
    if not recovery_records:
        suggestions.append(f"  · 缺少恢复活动记录，记得散步/手工/非屏幕活动")

    if suggestions:
        lines.extend(suggestions)
    else:
        lines.append(f"  ✅ 各项指标达标！保持节奏，继续积累职场资本")
    lines.append("")

    lines.append("╚══════════════════════════════════════╝")
    return "\n".join(lines)


def send_feishu_message(text, dry_run=False):
    """推送飞书消息"""
    if dry_run:
        print(text)
        return {"ok": True, "dry_run": True}

    result = _run_lark([
        "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--markdown", text,
        "--as", "user",
    ])

    if result.returncode == 0:
        return {"ok": True}
    else:
        return {"ok": False, "error": result.stderr}


def main():
    dry_run = "--dry-run" in sys.argv
    days = 7
    for arg in sys.argv[1:]:
        if arg.startswith("--days="):
            days = int(arg.split("=", 1)[1])

    print(f"📊 生成深度工作周报（{days}天）...")

    records = fetch_deep_work_records(days)
    print(f"  读取到 {len(records)} 条记录")

    report = generate_weekly_report(records, days)
    print("\n" + "=" * 50)
    print(report)
    print("=" * 50 + "\n")

    if not dry_run:
        print("📨 推送飞书消息...")
        result = send_feishu_message(report)
        if result.get("ok"):
            print("✅ 周报已推送")
        else:
            print(f"❌ 推送失败：{result.get('error')}")
    else:
        print("[DRY-RUN] 跳过推送")


if __name__ == "__main__":
    main()
