from datetime import datetime, timezone
import importlib

import pytest


def api():
    try:
        module = importlib.import_module('yushuos.scheduler')
    except ModuleNotFoundError:
        module = None
    assert module is not None, 'The trigger runtime must be implemented'
    return module


def test_cron_next_due_uses_frozen_timezone():
    trigger = {'type': 'cron', 'expression': '0 7 * * *', 'timezone': 'Asia/Shanghai'}
    assert api().next_due(trigger, '2026-10-01T00:00:00.000000Z') == '2026-10-01T23:00:00.000000Z'


def test_cron_sunday_zero_and_seven_and_posix_or():
    start = '2026-10-05T00:00:00.000000Z'
    for day in ('0', '7', 'sun'):
        assert api().next_due({'type':'cron', 'expression':f'0 7 * * {day}', 'timezone':'UTC'}, start) == '2026-10-11T07:00:00.000000Z'
    assert api().next_due({'type':'cron','expression':'0 7 1 * tue','timezone':'UTC'},start) == '2026-10-06T07:00:00.000000Z'


def test_dst_gap_skipped_and_overlap_fold_zero_only():
    gap = {'type':'cron','expression':'30 2 * * *','timezone':'America/New_York'}
    assert api().next_due(gap, '2026-03-08T00:00:00.000000Z') == '2026-03-09T06:30:00.000000Z'
    fold = {'type':'cron','expression':'30 1 * * *','timezone':'America/New_York'}
    first = api().next_due(fold, '2026-11-01T00:00:00.000000Z')
    assert first == '2026-11-01T05:30:00.000000Z'
    assert api().next_due(fold, first) == '2026-11-02T06:30:00.000000Z'
    assert api().next_due(fold, '2026-11-01T06:00:00.000000Z') == '2026-11-02T06:30:00.000000Z'


def test_interval_anchored_and_strictly_after():
    t = {'type':'interval','seconds':300,'anchor':'2026-10-01T00:00:00.000000Z'}
    assert api().next_due(t, t['anchor']) == '2026-10-01T00:05:00.000000Z'
    assert api().next_due(t, '2026-10-01T00:05:00.000000Z') == '2026-10-01T00:10:00.000000Z'


@pytest.mark.parametrize('expression', ['* * * * * *','0 0 31 2 *','@daily','0 0 * * 0#1','0 0 L * *','0 0 * * 5L'])
def test_cron_unsupported_or_impossible_rejected(expression):
    with pytest.raises(ValueError):
        api().next_due({'type':'cron','expression':expression,'timezone':'UTC'}, '2026-10-01T00:00:00.000000Z')
