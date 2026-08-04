"""C-9b habit 迁移测试。

验证 handlers/habit.py 与旧 handle_habit(1732-1824) 的 1:1 行为一致性。
覆盖：路由键 / true cut 信号 / 空内容帮助 / 各变量解析 / dry_run / 成功写入 / parity。
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
from 输入解析引擎.handlers import habit


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr or ""


class TestHabitRoute(unittest.TestCase):
    def test_route_key(self):
        key, _ = router._resolve_route_key("#习惯 每天背单词")
        self.assertEqual(key, "habit")

    def test_route_key_help(self):
        key, _ = router._resolve_route_key("#习惯")
        self.assertEqual(key, "habit")


class TestHabitCut(unittest.TestCase):
    def test_bridge_removed(self):
        self.assertFalse(
            hasattr(router, "_call_habit"),
            "legacy _call_habit bridge still present in router",
        )

    def test_map_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["habit"],
            habit.handle_habit,
        )


class TestHabitBehavior(unittest.TestCase):
    def test_empty_content_returns_help(self):
        res = habit.handle_habit("#习惯")
        self.assertEqual(res["type"], "habit_help")
        self.assertIn("习惯追踪", res["message"])

    def test_no_name_returns_error(self):
        res = habit.handle_habit("#习惯 【我是：测试者】")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("请指定习惯名称", res["message"])

    def test_basic_habit_create_dry_run(self):
        res = habit.handle_habit("#习惯 每天背单词", dry_run=True)
        self.assertEqual(res["type"], "habit_create")
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res["payload"]["习惯名称"], "每天背单词")
        self.assertEqual(res["payload"]["频率"], "每天")
        self.assertEqual(res["payload"]["当前连续天数"], 0)

    def test_with_all_variables_dry_run(self):
        text = ("#习惯 每天背20个单词 "
                "【我是：背词者】"
                "【在：早饭后在书桌前】"
                "【提示：单词本放桌面】"
                "【频率：每天】")
        res = habit.handle_habit(text, dry_run=True)
        self.assertEqual(res["type"], "habit_create")
        self.assertTrue(res.get("dry_run"))
        payload = res["payload"]
        self.assertEqual(payload["习惯名称"], "每天背20个单词")
        self.assertEqual(payload["身份声明"], "背词者")
        self.assertEqual(payload["执行意图"], "早饭后在书桌前")
        self.assertEqual(payload["提示位置"], "单词本放桌面")
        self.assertEqual(payload["频率"], "每天")

    def test_with_stacking_dry_run(self):
        text = "#习惯 冥想 【在刷牙之后】"
        res = habit.handle_habit(text, dry_run=True)
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res["payload"]["习惯叠加"], "刷牙")

    def test_custom_frequency_dry_run(self):
        text = "#习惯 每周跑步 【频率：每周2-3次】"
        res = habit.handle_habit(text, dry_run=True)
        self.assertEqual(res["payload"]["频率"], "每周2-3次")

    def test_invalid_frequency_defaults_to_每天(self):
        text = "#习惯 每天编程 【频率：每月】"
        res = habit.handle_habit(text, dry_run=True)
        self.assertEqual(res["payload"]["频率"], "每天")

    def test_successful_create(self):
        r = _FakeResult(0, "{}")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r):
            res = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(res["type"], "habit_create")
        self.assertIn("已创建", res["message"])
        self.assertIn("每天背单词", res["message"])

    def test_identity_in_message(self):
        r = _FakeResult(0, "{}")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r):
            res = habit.handle_habit("#习惯 每天背单词 【我是：背词者】")
        self.assertEqual(res["type"], "habit_create")
        self.assertIn("背词者", res["message"])

    def test_location_and_cue_in_message(self):
        r = _FakeResult(0, "{}")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r):
            res = habit.handle_habit("#习惯 阅读30分钟 【在：书桌前】【提示：书签在桌上】")
        self.assertEqual(res["type"], "habit_create")
        self.assertIn("执行意图", res["message"])
        self.assertIn("提示位置", res["message"])

    def test_write_failure(self):
        r = _FakeResult(1, "error!")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r):
            res = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("写入失败", res["error"])

    def test_exception_during_write(self):
        with mock.patch.object(habit, "_run_lark_cli", side_effect=RuntimeError("boom")):
            res = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("boom", res["error"])


class TestHabitParity(unittest.TestCase):
    def test_parity_empty(self):
        legacy = router._get_legacy()
        old = legacy.handle_habit("#习惯")
        new = habit.handle_habit("#习惯")
        self.assertEqual(old, new)

    def test_parity_basic(self):
        legacy = router._get_legacy()
        old = legacy.handle_habit("#习惯 每天背单词")
        new = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(old, new)

    def test_parity_dry_run(self):
        legacy = router._get_legacy()
        old = legacy.handle_habit("#习惯 每天背20个单词 【我是：背词者】【在：早饭后】【提示：桌面上】【频率：每天】", dry_run=True)
        new = habit.handle_habit("#习惯 每天背20个单词 【我是：背词者】【在：早饭后】【提示：桌面上】【频率：每天】", dry_run=True)
        self.assertEqual(old, new)

    def test_parity_no_name(self):
        legacy = router._get_legacy()
        old = legacy.handle_habit("#习惯 【我是：测试者】")
        new = habit.handle_habit("#习惯 【我是：测试者】")
        self.assertEqual(old, new)

    def test_parity_success_with_mock(self):
        legacy = router._get_legacy()
        r = _FakeResult(0, "{}")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit("#习惯 每天背单词")
            new = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(old, new)

    def test_parity_failure_with_mock(self):
        legacy = router._get_legacy()
        r = _FakeResult(1, "error!")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit("#习惯 每天背单词")
            new = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(old, new)

    def test_parity_full_variables_with_mock(self):
        legacy = router._get_legacy()
        text = ("#习惯 每天背20个单词 "
                "【我是：背词者】"
                "【在：早饭后在书桌前】"
                "【在刷牙之后】"
                "【提示：单词本放桌面】"
                "【频率：每天】")
        r = _FakeResult(0, "{}")
        with mock.patch.object(habit, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit(text)
            new = habit.handle_habit(text)
        self.assertEqual(old, new)

    def test_parity_exception_with_mock(self):
        legacy = router._get_legacy()
        with mock.patch.object(habit, "_run_lark_cli", side_effect=RuntimeError("boom")), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=RuntimeError("boom")):
            old = legacy.handle_habit("#习惯 每天背单词")
            new = habit.handle_habit("#习惯 每天背单词")
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main(verbosity=2)
