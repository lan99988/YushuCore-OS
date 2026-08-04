"""Body OS handler.

Phase 1 入口适配层：只做指令归类与用户可读反馈，不直接写飞书 Base。
真正的训练/营养/恢复/分析能力由 yushu_10 BodyController 调度。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BODY_TOOLS_PATH = PROJECT_ROOT / "08_工具脚本（Tools）" / "身体管理"
GARMIN_SUMMARY_PATH = (
    BODY_TOOLS_PATH / "body_os_garmin_summary.json"
)
MANUAL_TRAINING_LOG_PATH = (
    PROJECT_ROOT
    / "04_数据中心（Data）"
    / "运行状态（Runtime）"
    / "manual_training_log.json"
)

if str(BODY_TOOLS_PATH) not in sys.path:
    sys.path.insert(0, str(BODY_TOOLS_PATH))

from nutrition_policy import derive_nutrition_policy  # noqa: E402
from recovery_policy import derive_recovery_policy  # noqa: E402
from training_log import append_training_entry, parse_training_entry  # noqa: E402


PREFIX_TO_MODULE = {
    "#身体": "controller",
    "#训练": "strength",
    "#营养": "nutrition",
    "#恢复": "recovery",
    "#体测": "analytics",
}


MODULE_LABEL = {
    "controller": "身体总管",
    "strength": "力量塑形",
    "nutrition": "营养管理",
    "recovery": "恢复管理",
    "analytics": "身体分析",
}


def _load_garmin_summary() -> dict | None:
    if not GARMIN_SUMMARY_PATH.exists():
        return None
    try:
        return json.loads(GARMIN_SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _format_garmin_summary(summary_payload: dict | None) -> str:
    if not summary_payload:
        return ""
    date_range = summary_payload.get("date_range", {})
    summary = summary_payload.get("summary", {})
    activity_counts = summary.get("activity_type_counts", {})
    parts = [
        f"Garmin近一年：{date_range.get('start')} 至 {date_range.get('end')}",
        f"Energy {summary.get('energy_days')}天",
        f"训练{summary.get('training_log_count')}次",
    ]
    if activity_counts.get("running") is not None:
        parts.append(f"跑步{activity_counts.get('running')}次")
    if activity_counts.get("strength") is not None:
        parts.append(f"力量{activity_counts.get('strength')}次")
    if summary.get("avg_sleep_hours") is not None:
        parts.append(f"平均睡眠{summary.get('avg_sleep_hours')}小时")
    if summary.get("avg_readiness_score") is not None:
        parts.append(f"平均准备度{summary.get('avg_readiness_score')}")
    if summary.get("avg_steps") is not None:
        parts.append(f"平均步数{summary.get('avg_steps')}")
    if summary.get("excluded_no_data_days"):
        parts.append(f"无统计日已排除{summary.get('excluded_no_data_days')}天")
    lines = ["；".join(parts) + "。"]
    today_context = summary_payload.get("today_energy_context") or {}
    if today_context:
        requested = today_context.get("requested_date")
        stale_note = ""
        if requested and not today_context.get("is_requested_date", True):
            stale_note = f"（{requested}无有效统计，未纳入判断）"
        lines.append(
            "最新有效Garmin日："
            f"{today_context.get('date')}{stale_note}；"
            f"精神状态：{today_context.get('mental_state_label')}；"
            f"学习负载：{today_context.get('study_load_label')}；"
            f"身体可用能量{today_context.get('body_battery_score', today_context.get('body_battery'))}；"
            f"建议：{today_context.get('task_policy')} "
            f"依据：{today_context.get('reason')}"
        )
    training_context = summary_payload.get("today_training_context") or {}
    if training_context:
        warning_messages = [
            item.get("message")
            for item in training_context.get("warnings", [])
            if isinstance(item, dict) and item.get("message")
        ]
        warning_text = f"；风险：{'；'.join(warning_messages)}" if warning_messages else ""
        scope_note = training_context.get("scope_note")
        scope_text = f"；{scope_note}" if scope_note else ""
        lines.append(
            "训练建议："
            f"{training_context.get('training_load_label')}；"
            f"{training_context.get('recommendation')}"
            f"{warning_text}{scope_text}"
        )
        # 肌群信息
        today_mg = training_context.get("today_muscle_groups")
        if today_mg:
            mg_text = "、".join(str(g) for g in today_mg)
            mv = training_context.get("today_muscle_volume") or {}
            vol_parts = [f"{k}{v:g}kg" for k, v in sorted(mv.items())]
            vol_text = f"（{'；'.join(vol_parts)}）" if vol_parts else ""
            lines.append(f"今日训练肌群：{mg_text}{vol_text}")
        mg_risk = training_context.get("muscle_group_risk")
        if mg_risk:
            lines.append("⚠ 肌群重复风险：48h 内有已训肌群，建议换组。")
    return "\n".join(lines)


def _strip_prefix(raw_text: str) -> tuple[str, str]:
    text = raw_text.strip()
    for prefix, module in sorted(PREFIX_TO_MODULE.items(), key=lambda item: -len(item[0])):
        if text.startswith(prefix):
            return module, text[len(prefix):].strip()
    return "controller", text


def _format_training_entry(content: str, dry_run: bool) -> str:
    entry = parse_training_entry(f"#训练 {content}")
    if not dry_run:
        append_training_entry(MANUAL_TRAINING_LOG_PATH, entry)

    activity_label = {
        "strength": "力量",
        "running": "跑步",
        "mobility": "活动度",
        "other": "其他",
    }.get(entry.get("activity_type"), str(entry.get("activity_type") or "其他"))
    parts = [f"训练记录草稿：{activity_label}"]
    if entry.get("duration_min") is not None:
        parts.append(f"{entry['duration_min']}分钟")
    if entry.get("distance_km") is not None:
        parts.append(f"{entry['distance_km']}公里")
    if entry.get("exercises"):
        exercise_text = "、".join(
            f"{item['name']} {item['weight_kg']:g}kgx{item['reps']}x{item['sets']}"
            for item in entry["exercises"]
        )
        parts.append(f"动作：{exercise_text}")
    if entry.get("total_volume") is not None:
        parts.append(f"总容量{entry['total_volume']:g}")
    # 肌群信息
    if entry.get("muscle_groups"):
        mg_text = "、".join(str(g) for g in entry["muscle_groups"])
        mv = entry.get("muscle_volume") or {}
        vol_parts = [f"{k}{v:g}kg" for k, v in sorted(mv.items())]
        vol_text = f"（{'；'.join(vol_parts)}）" if vol_parts else ""
        parts.append(f"肌群：{mg_text}{vol_text}")
    if not dry_run:
        parts.append("已写入本地 manual_training_log.json")
    return "；".join(parts)


def _format_recovery_advice(summary_payload: dict | None) -> str:
    summary_payload = summary_payload or {}
    policy = derive_recovery_policy(
        summary_payload.get("today_energy_context"),
        summary_payload.get("today_training_context"),
    )
    warning_text = "；".join(
        item.get("message", "")
        for item in policy.get("warnings", [])
        if isinstance(item, dict) and item.get("message")
    )
    warning_suffix = f"\n依据：{warning_text}" if warning_text else ""
    return (
        "恢复建议："
        f"{policy.get('recovery_label')}；"
        f"{policy.get('recommendation')}"
        f"{warning_suffix}"
    )


def _format_nutrition_advice(summary_payload: dict | None) -> str:
    summary_payload = summary_payload or {}
    policy = derive_nutrition_policy(
        training_context=summary_payload.get("today_training_context")
    )
    hints = "；".join(
        item.get("message", "")
        for item in policy.get("hints", [])
        if isinstance(item, dict) and item.get("message")
    )
    hint_suffix = f"\n补充：{hints}" if hints else ""
    return (
        "营养建议："
        f"蛋白质{policy.get('protein_target_g')}g左右；"
        f"饮水{policy.get('water_target_ml')}ml左右；"
        f"{policy.get('recommendation')}"
        f"{hint_suffix}"
    )


def handle_body_os(raw_text, dry_run=False):
    """处理 Body OS Phase 1 指令。

    当前只生成可确认的解析结果；飞书 Base 表创建前不做写入。
    """
    module, content = _strip_prefix(raw_text)
    label = MODULE_LABEL[module]
    content = content or "（未提供具体内容）"

    if module == "controller":
        action = "将综合 Energy、TrainingLog、NutritionLog、BodyMetrics 与 Garmin 映射结果给出今日建议。"
    elif module == "strength":
        action = _format_training_entry(content, dry_run=dry_run)
    elif module == "nutrition":
        action = _format_nutrition_advice(_load_garmin_summary())
    elif module == "recovery":
        action = _format_recovery_advice(_load_garmin_summary())
    else:
        action = "将作为 BodyMetrics 或 7 天趋势分析输入处理。"

    mode = "测试模式，未写入 Base。" if dry_run else "当前 Phase 1 表尚未确认，未自动写入 Base。"
    garmin_context = _format_garmin_summary(_load_garmin_summary()) if module == "controller" else ""
    context_line = f"\n{garmin_context}" if garmin_context else ""
    return {
        "ok": True,
        "type": "body_os",
        "module": module,
        "dry_run": dry_run,
        "message": f"{label}已接收：{content}\n{action}{context_line}\n{mode}",
    }
