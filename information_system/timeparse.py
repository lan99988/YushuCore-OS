"""时间表达式解析（P1-6 修复）。

职责：把中文相对/绝对时间表述解析为**可比较的时间点或时间窗口**。
- 纯函数，`now` 可注入 → 测试确定性。
- 不确定就不猜：时间窗口（"下周"）只给 window，不伪造精确 deadline；
  模糊表述（"尽快/以后"）不产出任何时间点。
- 时区：使用 `now` 的本地时区偏移（本机 +08:00）。

约定（写入 InformationObject.json 前需知）：
- `precision=minute`：明确日期 + 时刻 → deadline 为该时刻；
- `precision=date`：只有日期 → deadline 为该日 23:59（当天结束）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

PERIOD_HOURS = {"凌晨": 0, "早上": 0, "早晨": 0, "上午": 0, "中午": 12, "下午": 12, "傍晚": 12, "晚上": 12}

_TIME_RE = re.compile(
    r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)?\s*"
    r"(\d{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*(?:[:：点时])\s*"
    r"(\d{1,2})?\s*分?"
)

_DATE_REL_RE = re.compile(r"(大后天|后天|明天|明日|今天|今日|今晚)")
_WEEKDAY_RE = re.compile(r"(下下|下|本|这)?\s*周\s*([一二三四五六日天])")
_WEEKDAY_BARE_RE = re.compile(r"(?<![下本这])周\s*([一二三四五六日天])")
_WEEKEND_RE = re.compile(r"(下下|下|本|这)?\s*周末")
_WEEK_SPAN_RE = re.compile(r"(下下|下|本|这)\s*周(?!\s*[一二三四五六日天末])")
_MONTH_SPAN_RE = re.compile(r"(下个|下|本|这个|这)\s*月(?!\s*\d)")
_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_ISO_DATE_RE = re.compile(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})")
_FUZZY_RE = re.compile(r"尽快|近期|以后|将来|某天|迟早|有空")


def _cn_to_int(text: str) -> int | None:
    """中文数字转整数（支持 十/十一/二十/二十三）。"""
    if text.isdigit():
        return int(text)
    if not text:
        return None
    if "十" not in text:
        if all(char in CN_DIGITS for char in text):
            value = 0
            for char in text:
                value = value * 10 + CN_DIGITS[char]
            return value
        return None
    head, _, tail = text.partition("十")
    tens = CN_DIGITS.get(head, 1) if head else 1
    ones = CN_DIGITS.get(tail, 0) if tail else 0
    return tens * 10 + ones


@dataclass(frozen=True)
class TimeResolution:
    label: str
    kind: str  # point | window | fuzzy
    deadline: str = ""
    precision: str = ""  # minute | date
    window_start: str = ""
    window_end: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "kind": self.kind,
            "deadline": self.deadline,
            "precision": self.precision,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "reason": self.reason,
        }


def _tzinfo_of(moment: datetime):
    offset = moment.astimezone().utcoffset() or timedelta(0)
    return timezone(offset)


def _iso(moment: datetime, tz) -> str:
    return moment.replace(tzinfo=tz, microsecond=0).isoformat()


def _start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_time_of_day(text: str) -> tuple[int, int, str] | None:
    """返回 (hour, minute, 命中文本)。无时刻返回 None。"""
    match = _TIME_RE.search(text)
    if match is None:
        return None
    period, hour_text, minute_text = match.group(1), match.group(2), match.group(3)
    hour = _cn_to_int(hour_text)
    if hour is None or hour > 24:
        return None
    minute = _cn_to_int(minute_text) if minute_text else 0
    if minute is None or minute > 59:
        minute = 0
    if period in PERIOD_HOURS and hour < 12:
        # 时段前缀只做 12/24 小时制换算（"晚上 8 点" → 20 点），不是加一个基准时刻
        hour += PERIOD_HOURS[period]
    if hour >= 24:
        hour -= 24
    return hour, minute, match.group(0).strip()


def _weekday_target(moment: datetime, prefix: str, weekday: int) -> datetime:
    base = _start_of_day(moment)
    delta_to_monday = -base.weekday()
    if prefix == "下":
        target_monday = base + timedelta(days=delta_to_monday + 7)
    elif prefix == "下下":
        target_monday = base + timedelta(days=delta_to_monday + 14)
    else:  # 本 / 这 / 裸周X：本周内，已过则按下周
        target_monday = base + timedelta(days=delta_to_monday)
        if prefix is None:
            candidate = target_monday + timedelta(days=weekday)
            if candidate.date() < base.date():
                target_monday = base + timedelta(days=delta_to_monday + 7)
    return target_monday + timedelta(days=weekday)


def resolve_time(text: str, *, now: datetime | None = None) -> TimeResolution | None:
    """解析时间表述。无法确定时返回 None（本项目不猜时间）。"""
    if not text or not text.strip():
        return None
    moment = now or datetime.now()
    tz = _tzinfo_of(moment)
    clock = _parse_time_of_day(text)
    hour, minute = (clock[0], clock[1]) if clock else (None, None)
    clock_label = clock[2] if clock else ""

    def _point(date_value: datetime, reason: str) -> TimeResolution:
        if hour is None:
            deadline = date_value.replace(hour=23, minute=59)
            precision = "date"
        else:
            deadline = date_value.replace(hour=hour, minute=minute or 0)
            precision = "minute"
        label = (f"{reason} {clock_label}").strip()
        return TimeResolution(
            label=label, kind="point", deadline=_iso(deadline, tz), precision=precision,
            reason=f"{reason}；{'精确到分钟' if precision == 'minute' else '仅有日期，取当日结束'}",
        )

    base = _start_of_day(moment)

    # 1) 绝对日期（YYYY-MM-DD / MM月DD日）优先级最高
    iso = _ISO_DATE_RE.search(text)
    if iso:
        candidate = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return _point(candidate, iso.group(0).strip())
    month_day = _MONTH_DAY_RE.search(text)
    if month_day:
        month, day = int(month_day.group(1)), int(month_day.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            candidate = datetime(moment.year, month, day)
            if candidate.date() < base.date():
                candidate = candidate.replace(year=moment.year + 1)
            return _point(candidate, month_day.group(0).strip())

    # 2) 相对日（今天/明天/后天/大后天）
    relative = _DATE_REL_RE.search(text)
    if relative:
        offsets = {"今天": 0, "今日": 0, "今晚": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}
        return _point(base + timedelta(days=offsets[relative.group(1)]), relative.group(0).strip())

    # 3) 周内具体某天
    weekday = _WEEKDAY_RE.search(text) or _WEEKDAY_BARE_RE.search(text)
    if weekday:
        groups = weekday.groups()
        prefix = groups[0] if len(groups) > 1 else None
        target = _weekday_target(moment, prefix, WEEKDAY_MAP[groups[-1]])
        return _point(target, weekday.group(0).strip())

    # 4) 周末
    weekend = _WEEKEND_RE.search(text)
    if weekend:
        prefix = weekend.group(1)
        target = _weekday_target(moment, prefix, 5)
        return _point(target, weekend.group(0).strip())

    # 5) 周/月窗口（不伪造精确时间点）
    span = _WEEK_SPAN_RE.search(text) or _MONTH_SPAN_RE.search(text)
    if span:
        token = span.group(0).strip()
        prefix = span.group(1)
        if "月" in token:
            if prefix in {"下", "下个"}:
                start = _start_of_day((base.replace(day=1) + timedelta(days=32)).replace(day=1))
            else:
                start = base.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        else:
            if prefix == "下":
                start = base + timedelta(days=-base.weekday() + 7)
            elif prefix == "下下":
                start = base + timedelta(days=-base.weekday() + 14)
            else:
                start = base + timedelta(days=-base.weekday())
            end = start + timedelta(days=6)
        return TimeResolution(
            label=token, kind="window",
            window_start=_iso(start, tz), window_end=_iso(end.replace(hour=23, minute=59), tz),
            reason=f"「{token}」是时间范围而非时间点，只给窗口不给 deadline",
        )

    # 6) 模糊表述
    fuzzy = _FUZZY_RE.search(text)
    if fuzzy:
        return TimeResolution(
            label=fuzzy.group(0), kind="fuzzy",
            reason=f"「{fuzzy.group(0)}」无法确定具体时间，不产出 deadline",
        )
    return None
