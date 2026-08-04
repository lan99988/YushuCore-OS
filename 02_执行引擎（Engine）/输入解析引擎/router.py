"""
路由层（Step2-4-A）

职责：替代 main() 内的 if/elif 巨型分发逻辑。

设计原则（搬家不装修）：
- 本文件只做「前缀 -> 处理函数」的分发，不搬运任何业务计算。
- 所有业务仍委托给冻结的旧模块 input_parser_old 的对应函数（通过 legacy 桥）。
- 后续 Step2-4-B/C 会把 handler 落到 handlers/ 模块，届时只需把 ROUTES 的
  目标从 legacy 桥改为新 handler 模块，main() 控制流不变。

old main() 控制流（2395 行单体）的等价表达：
  1. "#临时" 短路 -> lightweight
  2. 特殊分支门（table_name is None 或 startswith #精力）-> 按 ROUTES startswith 匹配
  3. 否则走标准路径（detect -> extract -> build -> insert -> format + 详情块）
"""

import os
import sys
import importlib
import importlib.util

from .handlers import lightweight, energy, config_cmd, hatch, attention_audit, sync_taskbox, review, deep_plan, deep_record, deep_work, habit_checkin, habit, habit_progress, schedule_calendar, competition, body_os

# 标准路径前缀（走 build_record 通用流程，由 detect_prefix 识别）
# 注：仅作文档参考，实际路由以 detect_prefix 返回的 table_name 为准。
STANDARD_PREFIXES = {
    "#任务", "#灵感", "#Bug",
    "#账单", "#财务",
    "#社交", "#关系", "#人脉",
    "#创作", "#作品",
    "#知识", "#笔记", "#学",
}

# 特殊指令路由表：前缀 -> 路由键（顺序敏感，长前缀在前）
ROUTES = {
    "#临时": "lightweight",
    "#精力": "energy",
    "#配置": "config_cmd",
    "#孵化": "hatch",
    "#复盘": "review",
    "#排程到日历": "schedule_calendar",
    "#日历": "schedule_calendar",
    "#深度规划": "deep_plan",
    "#深度记录": "deep_record",
    "#深度": "deep_work",
    "#注意力审计": "attention_audit",
    "#习惯打卡": "habit_checkin",
    "#习惯进度": "habit_progress",
    "#习惯": "habit",
    "#比赛": "competition",
    "#身体": "body_os",
    "#训练": "body_os",
    "#营养": "body_os",
    "#恢复": "body_os",
    "#体测": "body_os",
    "#同步任务框": "sync_taskbox",
}

# 无法识别时向用户展示的前缀清单（与旧 main 保持一致）
_ALL_PREFIXES_HINT = [
    "#任务", "#灵感", "#Bug", "#精力", "#配置", "#账单/#财务",
    "#社交/#关系/#人脉", "#创作/#作品", "#知识/#笔记/#学",
    "#深度/规划/记录", "#注意力审计", "#习惯/习惯打卡",
    "#排程到日历/#日历", "#比赛", "#身体/#训练/#营养/#恢复/#体测",
    "#临时", "#同步任务框",
]

_LEGACY_MODULE = None


def _get_legacy():
    """懒加载冻结的旧模块 input_parser_old，作为业务委托源。"""
    global _LEGACY_MODULE
    if _LEGACY_MODULE is None:
        here = os.path.dirname(os.path.abspath(__file__))
        old_path = os.path.join(here, "input_parser_old.py")
        spec = importlib.util.spec_from_file_location("_input_parser_legacy", old_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LEGACY_MODULE = mod
    return _LEGACY_MODULE


def _resolve_route_key(raw_text):
    """返回 (route_key, table_name)。

    route_key 含义：
      - "unknown"       : 无法识别（旧 main 的 else 分支）
      - None            : 走标准路径（standard_record）
      - 其他字符串       : ROUTE_HANDLERS 中的键，对应特殊 handler
    """
    legacy = _get_legacy()

    # 1. 临时任务短路
    if "#临时" in raw_text:
        return "lightweight", None

    # 2. 检测标准前缀
    table_name, _ = legacy.detect_prefix(raw_text)

    # 3. 特殊分支门：table_name 为 None 或显式 #精力
    if table_name is None or raw_text.startswith("#精力"):
        for prefix, key in ROUTES.items():
            if prefix != "#临时" and raw_text.startswith(prefix):
                return key, table_name
        return "unknown", table_name

    # 4. 标准路径
    return None, table_name


# ===================== legacy 桥：每个路由键委托旧函数 =====================
# 仅余 _call_standard 桥 — 展示层兼容保留（标准记录详情块），Phase 5 治理。
# 所有业务 handler 已迁至 handlers/ 模块。

def _call_standard(raw_text, dry_run):
    """标准路径：Step2-4-B 起委托 handlers.standard_record（真正切断旧 main）。

    仅做「解析 table_name + 调用新 handler」，不再内联标准路径业务逻辑。
    ROUTES / 其他特殊 handler / 输出编排（dispatch 的 format_output + 详情块）均不变。
    """
    legacy = _get_legacy()
    table_name, _ = legacy.detect_prefix(raw_text)
    from .handlers import standard_record
    return standard_record.handle_standard_record(table_name, raw_text, dry_run=dry_run)


def _format_output(result):
    if result.get("type") == "body_os":
        return f"[Body OS]\n{result['message']}"
    return _get_legacy().format_output(result)


# 路由键 -> 处理函数（静态表，便于测试以 patch.dict 覆盖单个键）
ROUTE_HANDLERS = {
    "lightweight": lightweight.handle_lightweight_task,
    "energy": energy.handle_energy_status,
    "config_cmd": config_cmd.handle_config_cmd,
    "hatch": hatch.handle_hatch,
    "review": review.handle_review,
    "schedule_calendar": schedule_calendar.handle_schedule_calendar,
    "deep_plan": deep_plan.handle_deep_plan,
    "deep_record": deep_record.handle_deep_record,
    "deep_work": deep_work.handle_deep_work,
    "attention_audit": attention_audit.handle_attention_audit,
    "habit_checkin": habit_checkin.handle_habit_checkin,
    "habit_progress": habit_progress.handle_habit_progress,
    "habit": habit.handle_habit,
    "competition": competition.handle_competition,
    "body_os": body_os.handle_body_os,
    "sync_taskbox": sync_taskbox.handle_sync_taskbox,
    "standard_record": _call_standard,
}


def dispatch(raw_text, dry_run=False):
    """替代 main() 的分发逻辑。

    返回最终格式化输出字符串（与旧 main 的 print 内容一致）。
    特殊指令 / 未知指令会调用 sys.exit（与旧 main 等价），测试时须 patch sys.exit。
    """
    legacy = _get_legacy()
    route_key, table_name = _resolve_route_key(raw_text)

    if route_key == "unknown":
        print(f"⚠️ 无法识别的指令。\n支持的前缀：{' '.join(_ALL_PREFIXES_HINT)}")
        sys.exit(1)

    if route_key is None:
        # 标准路径（无 sys.exit，与旧 main 一致）
        result = _call_standard(raw_text, dry_run=dry_run)
        output = _format_output(result)
        print(output)
        if dry_run:
            vars = legacy.extract_variables(raw_text)
            title = legacy.extract_main_content(raw_text)
            record = legacy.build_record(table_name, title, vars, raw_text=raw_text)
            print(f"\n解析详情：")
            print(f"  目标表：{table_name}")
            print(f"  标题：{title}")
            print(f"  变量：{legacy.json.dumps(vars, ensure_ascii=False)}")
            print(f"  记录：{legacy.json.dumps(record, ensure_ascii=False, indent=2)}")
        return output

    # 特殊指令（等价旧 main 各分支的 print + sys.exit(0)）
    handler = ROUTE_HANDLERS[route_key]
    result = handler(raw_text, dry_run=dry_run)
    output = _format_output(result)
    print(output)
    sys.exit(0)
