"""C-10b schedule_calendar 迁移测试。

验证 handlers/schedule_calendar.py 与旧 handle_schedule_to_calendar(1287-1356) 的 1:1 行为一致性。
编排型 handler：调用 daily_scheduler + calendar_sync 跨引擎模块。

三层测试策略：
  Layer 1: handler 行为（mock daily_scheduler + calendar_sync 返回值）
  Layer 2: Router cut + 路由键
  Layer 3: 跨引擎 mock 链路验证
"""

import os
import sys
import json
import unittest
import unittest.mock as mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import schedule_calendar


def _make_empty_tasks():
    """模拟 daily_scheduler.get_today_tasks 返回空列表"""
    return []


def _make_tasks():
    return [
        {"id": "1", "title": "学习数学", "status": "pending"},
        {"id": "2", "title": "背英语单词", "status": "pending"},
    ]


def _make_baselines():
    return [
        {"subject": "数学", "daily_hours": 2.0},
        {"subject": "英语", "daily_hours": 1.0},
    ]


def _make_schedule():
    return {
        "timeline": [
            {"slot": "高效段①", "time": "09:00-10:30", "subject": "数学", "type": "deep"},
            {"slot": "高效段②", "time": "10:45-11:45", "subject": "英语", "type": "shallow"},
        ],
        "summary": "今日排程",
    }


def _make_cal_ok(created=2):
    return {
        "ok": True,
        "created": created,
        "events": [
            {"event_id": "evt1", "summary": "数学", "start": "09:00", "end": "10:30"},
            {"event_id": "evt2", "summary": "英语", "start": "10:45", "end": "11:45"},
        ],
        "conflicts": [],
        "summary": f"已创建 {created} 个事件",
    }


def _make_cal_conflict():
    return {
        "ok": True,
        "created": 1,
        "events": [{"event_id": "evt1", "summary": "数学", "start": "09:00", "end": "10:30"}],
        "conflicts": [
            {
                "slot": "高效段②",
                "time": "10:45-11:45",
                "conflicting_events": [{"summary": "已有会议", "start": "10:30", "end": "12:00"}],
            }
        ],
        "summary": "部分同步成功",
    }


class _InjectModules:
    """上下文管理器：将 mock 模块注入 sys.modules，覆盖可能已缓存的真实模块。

    策略：保存真实模块引用 → 从 sys.modules 移除 → 注入 mock → 恢复真实模块。
    确保懒导入 `from daily_scheduler import ...` 命中 mock 而非真实模块。
    """

    def __init__(self, daily_scheduler=None, calendar_sync=None):
        self.daily = daily_scheduler or mock.MagicMock()
        self.calendar = calendar_sync or mock.MagicMock()
        self._saved = {}
        self._added = set()

    def __enter__(self):
        for name, mock_mod in [("daily_scheduler", self.daily), ("calendar_sync", self.calendar)]:
            self._saved[name] = sys.modules.pop(name, None)
            sys.modules[name] = mock_mod
            self._added.add(name)
        return self

    def __exit__(self, *args):
        for name in list(self._added):
            sys.modules.pop(name, None)
            if self._saved.get(name) is not None:
                sys.modules[name] = self._saved[name]
        self._added.clear()


# ========== Layer 1: Handler Behavior ==========


class TestScheduleCalendarBehavior(unittest.TestCase):
    """Layer 1: handler 行为测试（mock daily_scheduler + calendar_sync 返回值）"""

    def test_no_tasks(self):
        """无待办任务 → \"🎉 今天没有待办任务\""""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_empty_tasks()
        with _InjectModules(daily_scheduler=ds):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")
        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "calendar")
        self.assertIn("没有待办任务", res["message"])

    def test_dry_run(self):
        """dry_run=True → dry_run 标志 + 消息含 TEST"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock()
        cs.sync_schedule_to_calendar.return_value = _make_cal_ok()

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历 --dry-run", dry_run=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "calendar")
        self.assertTrue(res.get("dry_run"))
        self.assertIn("TEST", res["message"])
        # 验证 dry_run 透传到 generate_schedule（作为位置参数第4个）
        self.assertTrue(ds.generate_schedule.called)
        call_gen = ds.generate_schedule.call_args
        self.assertTrue(
            call_gen[0][3] if len(call_gen[0]) > 3 else call_gen[1].get("dry_run"),
            f"dry_run not found in generate_schedule call: {call_gen}"
        )
        # 验证 dry_run 透传到 sync_schedule_to_calendar（关键字参数）
        self.assertTrue(cs.sync_schedule_to_calendar.called)
        call_sync = cs.sync_schedule_to_calendar.call_args
        self.assertTrue(
            call_sync[1].get("dry_run"),
            f"dry_run not found in sync call kwargs: {call_sync}"
        )

    def test_success_create(self):
        """正常创建日历事件"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock()
        cs.sync_schedule_to_calendar.return_value = _make_cal_ok(created=2)

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "calendar")
        self.assertIn("已同步 2 个时段", res["message"])

    def test_conflicts_detected(self):
        """冲突检测 → 消息含冲突信息"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock()
        cs.sync_schedule_to_calendar.return_value = _make_cal_conflict()

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        self.assertTrue(res["ok"])
        self.assertIn("检测到", res["message"])
        self.assertIn("冲突", res["message"])

    def test_empty_timeline(self):
        """排程无时段 → 提示信息"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = {"timeline": []}

        with _InjectModules(daily_scheduler=ds):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        self.assertTrue(res["ok"])
        self.assertIn("没有可写入日历的时段", res["message"])

    def test_import_error(self):
        """ImportError → ok=False + 错误消息"""
        # 移除每日排程引擎路径使懒导入失败
        with mock.patch.object(schedule_calendar, "_ensure_schedule_engine_path"):
            saved_paths = [p for p in sys.path if "每日排程引擎" in p]
            for p in saved_paths:
                sys.path.remove(p)
            try:
                res = schedule_calendar.handle_schedule_calendar("#排程到日历")
            finally:
                sys.path.extend(saved_paths)

        self.assertFalse(res["ok"])
        self.assertEqual(res["type"], "calendar")
        self.assertIn("日历同步模块未安装", res["error"])

    def test_exception(self):
        """异常 → ok=False + 错误消息"""
        ds = mock.MagicMock()
        ds.get_today_tasks.side_effect = Exception("飞书连接超时")

        with _InjectModules(daily_scheduler=ds):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        self.assertFalse(res["ok"])
        self.assertEqual(res["type"], "calendar")
        self.assertIn("飞书连接超时", res["error"])

    def test_no_output_no_conflicts(self):
        """日历同步返回无 created 无 conflicts → 默认消息"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock()
        cs.sync_schedule_to_calendar.return_value = {"ok": True, "created": 0, "conflicts": []}

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        self.assertTrue(res["ok"])
        self.assertIn("同步完成，无异常", res["message"])


# ========== Layer 2: Router Cut + Route Keys ==========


class TestScheduleCalendarRoute(unittest.TestCase):
    """Layer 2: 路由键验证"""

    def test_route_key_schedule_to_calendar(self):
        """#排程到日历 → schedule_calendar"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#排程到日历")
        self.assertEqual(key, "schedule_calendar")

    def test_route_key_calendar_abbrev(self):
        """#日历（简写）→ schedule_calendar"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#日历")
        self.assertEqual(key, "schedule_calendar")


class TestScheduleCalendarCutSignal(unittest.TestCase):
    """Layer 2: true cut 信号"""

    def test_call_bridge_removed(self):
        """router 无 _call_schedule_calendar"""
        self.assertFalse(hasattr(router, "_call_schedule_calendar"))

    def test_route_handlers_points_to_new(self):
        """ROUTE_HANDLERS['schedule_calendar'] 是新 handler"""
        self.assertIs(
            router.ROUTE_HANDLERS["schedule_calendar"],
            schedule_calendar.handle_schedule_calendar,
        )


# ========== Layer 3: Cross-engine Mock Chain ==========


class TestScheduleCalendarChain(unittest.TestCase):
    """Layer 3: 跨引擎 mock 链路验证 — 完整调用链"""

    def test_full_chain_dry_run(self):
        """全链路 dry_run：get_today_tasks → get_subject_baselines → generate_schedule → sync_schedule_to_calendar"""
        ds = mock.MagicMock(spec=[
            "get_today_tasks", "get_subject_baselines", "generate_schedule",
        ])
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock(spec=["sync_schedule_to_calendar"])
        cs.sync_schedule_to_calendar.return_value = _make_cal_ok()

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历", dry_run=True)

        # 验证 4 个函数都被调用
        ds.get_today_tasks.assert_called_once()
        ds.get_subject_baselines.assert_called_once()
        ds.generate_schedule.assert_called_once()
        cs.sync_schedule_to_calendar.assert_called_once()

        # 验证 dry_run 透传
        _, kwargs = cs.sync_schedule_to_calendar.call_args
        self.assertTrue(kwargs.get("dry_run"))

        # 验证返回格式
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("dry_run"))
        self.assertIn("slots", res.get("details", {}))

    def test_full_chain_success(self):
        """全链路成功"""
        ds = mock.MagicMock()
        ds.get_today_tasks.return_value = _make_tasks()
        ds.get_subject_baselines.return_value = _make_baselines()
        ds.generate_schedule.return_value = _make_schedule()

        cs = mock.MagicMock()
        cs.sync_schedule_to_calendar.return_value = _make_cal_ok(created=2)

        with _InjectModules(daily_scheduler=ds, calendar_sync=cs):
            res = schedule_calendar.handle_schedule_calendar("#排程到日历")

        ds.get_today_tasks.assert_called_once_with(mock.ANY)
        ds.get_subject_baselines.assert_called_once()
        ds.generate_schedule.assert_called_once()
        cs.sync_schedule_to_calendar.assert_called_once()

        self.assertTrue(res["ok"])
        self.assertIn("details", res)


if __name__ == "__main__":
    unittest.main()
