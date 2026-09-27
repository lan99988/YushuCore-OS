"""时间表达式解析测试（验收 P1-6 修复）。

全部用例注入固定 `now`，不依赖真实时钟；断言的"墙上时间"用带时区的 ISO 串
反解析后比字段，避免依赖本机时区。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from information_system.timeparse import TimeResolution, resolve_time

# 2026-09-16 是星期三
NOW = datetime(2026, 9, 16, 9, 0, 0)


def _wall(deadline: str) -> datetime:
    return datetime.fromisoformat(deadline).replace(tzinfo=None)


@pytest.mark.parametrize("text", ["", "   ", "把这段整理一下"])
def test_unresolvable_text_returns_none(text: str):
    assert resolve_time(text, now=NOW) is None


def test_point_with_clock_keeps_minute_precision():
    result = resolve_time("明天上午 10 点给客户发送报价。", now=NOW)
    assert result is not None
    assert result.kind == "point"
    assert result.precision == "minute"
    assert _wall(result.deadline) == datetime(2026, 9, 17, 10, 0)


def test_date_only_falls_back_to_end_of_day():
    result = resolve_time("明天提交周报。", now=NOW)
    assert result is not None
    assert result.kind == "point"
    assert result.precision == "date"
    assert _wall(result.deadline) == datetime(2026, 9, 17, 23, 59)


@pytest.mark.parametrize(
    ("text", "hour"),
    [("今天下午 3 点开会", 15), ("今天晚上 8 点复盘", 20), ("今天中午 12 点吃饭", 12)],
)
def test_period_prefix_shifts_to_24h_clock(text: str, hour: int):
    result = resolve_time(text, now=NOW)
    assert result is not None
    assert _wall(result.deadline).hour == hour


def test_chinese_numeral_hour():
    result = resolve_time("今天下午三点交材料。", now=NOW)
    assert result is not None
    assert _wall(result.deadline) == datetime(2026, 9, 16, 15, 0)


def test_next_week_weekday_lands_on_same_weekday_next_week():
    result = resolve_time("下周三交初稿。", now=NOW)
    assert result is not None
    target = _wall(result.deadline)
    assert target.date() == NOW.date() + timedelta(days=7)
    assert target.date().weekday() == 2


def test_weekend_prefix_targets_next_saturday():
    result = resolve_time("下周末去图书馆。", now=NOW)
    assert result is not None
    assert _wall(result.deadline).date().weekday() == 5


def test_week_window_does_not_fabricate_a_deadline():
    result = resolve_time("下周之前需要完成项目 A 的数据库迁移。", now=NOW)
    assert result is not None
    assert result.kind == "window"
    assert result.deadline == ""
    assert result.window_start and result.window_end
    start, end = _wall(result.window_start), _wall(result.window_end)
    assert (end - start).days == 6
    assert start.weekday() == 0
    assert "只给窗口不给 deadline" in result.reason


@pytest.mark.parametrize("text", ["尽快给我答复。", "以后再说。", "近期整理一下。"])
def test_fuzzy_expressions_never_produce_a_deadline(text: str):
    result = resolve_time(text, now=NOW)
    assert result is not None
    assert result.kind == "fuzzy"
    assert result.deadline == ""


def test_month_day_in_the_past_rolls_to_next_year():
    result = resolve_time("1月5日年检。", now=NOW)
    assert result is not None
    assert _wall(result.deadline).year == 2027


def test_absolute_iso_date_wins_over_relative_words():
    result = resolve_time("2027-03-01 之前给答复，别再拖到明天。", now=NOW)
    assert result is not None
    assert _wall(result.deadline).date().isoformat() == "2027-03-01"


def test_resolution_is_deterministic_for_same_now():
    first = resolve_time("明天上午 10 点给客户发送报价。", now=NOW)
    second = resolve_time("明天上午 10 点给客户发送报价。", now=NOW)
    assert isinstance(first, TimeResolution)
    assert first == second


def test_to_dict_is_serialisable_and_complete():
    payload = resolve_time("下周三 14:30 评审。", now=NOW).to_dict()
    assert set(payload) == {
        "label",
        "kind",
        "deadline",
        "precision",
        "window_start",
        "window_end",
        "reason",
    }
    assert payload["precision"] == "minute"
