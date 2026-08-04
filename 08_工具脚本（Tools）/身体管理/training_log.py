"""Manual Body OS training log helpers."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


EXERCISE_RE = re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z]+)\s*(?P<weight>\d+(?:\.\d+)?)kgx(?P<reps>\d+)x(?P<sets>\d+)", re.I)
DURATION_RE = re.compile(r"(?P<minutes>\d+(?:\.\d+)?)\s*(?:分钟|min)", re.I)
DISTANCE_RE = re.compile(r"(?P<km>\d+(?:\.\d+)?)\s*(?:公里|km)", re.I)

# 动作 → 肌群映射表（聚焦实际训练动作，不含 Garmin activityType）
MUSCLE_GROUP_MAP: dict[str, str] = {
    # 胸
    "卧推": "胸", "上斜卧推": "胸上", "下斜卧推": "胸下",
    "哑铃卧推": "胸", "哑铃飞鸟": "胸", "器械夹胸": "胸",
    # 背
    "引体向上": "背", "高位下拉": "背", "划船": "背",
    "杠铃划船": "背", "哑铃划船": "背", "坐姿划船": "背",
    # 腿
    "深蹲": "腿", "腿举": "腿", "腿弯举": "腿后",
    "腿屈伸": "腿前", "弓箭步": "腿", "保加利亚分腿蹲": "腿",
    "罗马尼亚硬拉": "腿后",
    # 下背/臀
    "硬拉": "下背/腿后", "臀推": "臀",
    # 肩
    "推举": "肩", "哑铃推举": "肩", "侧平举": "肩中",
    "前平举": "肩前", "面拉": "肩后",
    # 手臂
    "弯举": "二头", "哑铃弯举": "二头", "锤式弯举": "二头",
    "牧师凳弯举": "二头", "三头下压": "三头", "窄距卧推": "三头",
    "臂屈伸": "三头", "法式弯举": "三头",
    # 核心 / 全身
    "卷腹": "腹", "平板支撑": "核心", "悬垂举腿": "腹",
    "波比跳": "全身", "俯卧撑": "胸/三头",
}

# 动作 → 类型归类（方便推/拉/腿均衡分析）
MUSCLE_MOVE_TYPE: dict[str, str] = {
    "胸": "推", "胸上": "推", "胸下": "推", "胸/三头": "推",
    "三头": "推",
    "背": "拉", "肩后": "拉", "二头": "拉",
    "腿": "腿", "腿前": "腿", "腿后": "腿",
    "下背/腿后": "腿", "臀": "腿",
    "肩": "推", "肩中": "推", "肩前": "推",
    "腹": "核心", "核心": "核心", "全身": "全身",
}


def map_muscle_group(exercise_name: str) -> str:
    """将动作名称映射到肌群，未知动作返回 '未知'。"""
    return MUSCLE_GROUP_MAP.get(exercise_name.strip(), "未知")


def group_exercises_by_muscle(exercises: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按肌群归类训练动作。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ex in exercises:
        mg = map_muscle_group(ex.get("name", ""))
        ex["muscle_group"] = mg
        grouped.setdefault(mg, []).append(ex)
    return grouped


def aggregate_muscle_volume(exercises: list[dict[str, Any]]) -> dict[str, float]:
    """统计各肌群的总容量。"""
    volume: dict[str, float] = {}
    for ex in exercises:
        mg = map_muscle_group(ex.get("name", ""))
        vol = float(ex.get("weight_kg") or 0) * int(ex.get("reps") or 0) * int(ex.get("sets") or 0)
        volume[mg] = volume.get(mg, 0) + vol
    return {k: round(v, 2) for k, v in volume.items()}


def _today(today: str | None = None) -> str:
    return today or dt.date.today().isoformat()


def compute_strength_volume(exercises: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in exercises:
        total += float(item.get("weight_kg") or 0) * int(item.get("reps") or 0) * int(item.get("sets") or 0)
    return round(total, 2)


def parse_training_entry(raw_text: str, *, today: str | None = None) -> dict[str, Any]:
    content = raw_text.replace("#训练", "").strip()
    activity_type = "strength"
    if any(token in content for token in ("跑步", "慢跑", "有氧")):
        activity_type = "running"
    elif any(token in content for token in ("拉伸", "活动度", "瑜伽")):
        activity_type = "mobility"
    elif "力量" not in content and not EXERCISE_RE.search(content):
        activity_type = "other"

    duration = None
    duration_match = DURATION_RE.search(content)
    if duration_match:
        duration = int(float(duration_match.group("minutes")))

    distance = None
    distance_match = DISTANCE_RE.search(content)
    if distance_match:
        distance = float(distance_match.group("km"))

    exercises = []
    for match in EXERCISE_RE.finditer(content):
        exercises.append(
            {
                "name": match.group("name"),
                "weight_kg": float(match.group("weight")),
                "reps": int(match.group("reps")),
                "sets": int(match.group("sets")),
            }
        )
    # 标注肌群
    muscle_groups = set()
    for ex in exercises:
        mg = map_muscle_group(ex.get("name", ""))
        ex["muscle_group"] = mg
        muscle_groups.add(mg)
    muscle_volume = aggregate_muscle_volume(exercises) if exercises else {}
    total_volume = compute_strength_volume(exercises)

    return {
        "date": _today(today),
        "activity_type": activity_type,
        "session_name": content or "手动训练",
        "duration_min": duration,
        "distance_km": distance,
        "exercises": exercises,
        "muscle_groups": sorted(muscle_groups) if muscle_groups else None,
        "muscle_volume": muscle_volume or None,
        "total_volume": total_volume if exercises else None,
        "source": "manual",
        "notes": content,
    }


def append_training_entry(path: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = []
    else:
        payload = []
    if not isinstance(payload, list):
        payload = []
    payload.append(entry)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
