"""C-9a habit_checkin 迁移测试。

验证 handlers/habit_checkin.py 与旧 handle_habit_checkin(1827-1961) 的 1:1 行为一致性。
覆盖：路由键 / true cut 信号 / 空内容列表 / 打卡流程 / dry_run / 偶案 / parity。
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
from 输入解析引擎.handlers import habit_checkin


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr or ""


def _list_stdout(fields, data_rows, record_ids=None):
    return json.dumps({
        "data": {
            "fields": fields,
            "data": data_rows,
            "record_id_list": record_ids or [],
        }
    })


_ACTIVE_LIST_JSON = _list_stdout(
    ["习惯名称", "当前连续天数", "身份声明", "状态"],
    [["背单词", 7, "我是背词者", "进行中"]],
    ["rec_1"],
)
_EMPTY_LIST_JSON = _list_stdout(
    ["习惯名称", "当前连续天数", "身份声明", "状态"],
    [],
    [],
)
_CHECKIN_FOUND_JSON = _list_stdout(
    ["习惯名称", "当前连续天数", "身份声明", "状态"],
    [["背单词", 7, "我是背词者", "进行中"]],
    ["rec_1"],
)


class TestHabitCheckinRoute(unittest.TestCase):
    def test_route_key(self):
        self.assertEqual(
            router._resolve_route_key("#习惯打卡 背单词")[0], "habit_checkin"
        )
        self.assertEqual(
            router._resolve_route_key("#习惯打卡")[0], "habit_checkin"
        )


class TestHabitCheckinCut(unittest.TestCase):
    def test_bridge_removed(self):
        self.assertFalse(
            hasattr(router, "_call_habit_checkin"),
            "legacy _call_habit_checkin bridge still present in router",
        )

    def test_map_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["habit_checkin"],
            habit_checkin.handle_habit_checkin,
        )


class TestHabitCheckinBehavior(unittest.TestCase):
    def test_list_active_habits(self):
        r = _FakeResult(0, _ACTIVE_LIST_JSON)
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r):
            res = habit_checkin.handle_habit_checkin("#习惯打卡")
        self.assertEqual(res["type"], "habit_list")
        self.assertIn("今日待打卡习惯", res["message"])
        self.assertIn("背单词", res["message"])

    def test_list_no_active(self):
        r = _FakeResult(0, _EMPTY_LIST_JSON)
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r):
            res = habit_checkin.handle_habit_checkin("#习惯打卡")
        self.assertEqual(res["type"], "habit_list")
        self.assertIn("没有进行中的习惯", res["message"])

    def test_list_failure(self):
        r = _FakeResult(1, "")
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r):
            res = habit_checkin.handle_habit_checkin("#习惯打卡")
        self.assertEqual(res["type"], "habit_list")
        self.assertIn("暂无习惯数据", res["message"])

    def test_checkin_dry_run(self):
        r = _FakeResult(0, _CHECKIN_FOUND_JSON)
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r):
            res = habit_checkin.handle_habit_checkin("#习惯打卡 背单词", dry_run=True)
        self.assertEqual(res["type"], "habit_checkin")
        self.assertTrue(res.get("dry_run"))
        self.assertIn("背单词", res["message"])

    def test_checkin_not_found(self):
        r = _FakeResult(0, _list_stdout(
            ["习惯名称"], [["跑步"]], ["rec_x"]
        ))
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r):
            res = habit_checkin.handle_habit_checkin("#习惯打卡 不存在的习惯")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("未找到习惯", res["error"])

    def test_checkin_success(self):
        list_r = _FakeResult(0, _CHECKIN_FOUND_JSON)
        update_r = _FakeResult(0, '{}')
        with mock.patch.object(habit_checkin, "_run_lark_cli", side_effect=[list_r, update_r]):
            res = habit_checkin.handle_habit_checkin("#习惯打卡 背单词")
        self.assertEqual(res["type"], "habit_checkin")
        self.assertIn("已打卡", res["message"])
        self.assertIn("已连续 8 天", res["message"])  # 7+1

    def test_checkin_exception(self):
        with mock.patch.object(habit_checkin, "_run_lark_cli", side_effect=RuntimeError("boom")):
            res = habit_checkin.handle_habit_checkin("#习惯打卡 背单词")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("boom", res["error"])


class TestHabitCheckinParity(unittest.TestCase):
    def test_parity_list(self):
        legacy = router._get_legacy()
        r = _FakeResult(0, _ACTIVE_LIST_JSON)
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit_checkin("#习惯打卡")
            new = habit_checkin.handle_habit_checkin("#习惯打卡")
        self.assertEqual(old, new)

    def test_parity_checkin(self):
        legacy = router._get_legacy()
        list_r = _FakeResult(0, _CHECKIN_FOUND_JSON)
        update_r = _FakeResult(0, '{}')
        with mock.patch.object(habit_checkin, "_run_lark_cli", side_effect=[list_r, update_r]), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=[list_r, update_r]):
            old = legacy.handle_habit_checkin("#习惯打卡 背单词")
            new = habit_checkin.handle_habit_checkin("#习惯打卡 背单词")
        self.assertEqual(old, new)

    def test_parity_dry_run(self):
        legacy = router._get_legacy()
        r = _FakeResult(0, _CHECKIN_FOUND_JSON)
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit_checkin("#习惯打卡 背单词", dry_run=True)
            new = habit_checkin.handle_habit_checkin("#习惯打卡 背单词", dry_run=True)
        self.assertEqual(old, new)

    def test_parity_list_fail(self):
        legacy = router._get_legacy()
        r = _FakeResult(1, "")
        with mock.patch.object(habit_checkin, "_run_lark_cli", return_value=r), \
             mock.patch.object(legacy, "_run_lark_cli", return_value=r):
            old = legacy.handle_habit_checkin("#习惯打卡")
            new = habit_checkin.handle_habit_checkin("#习惯打卡")
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main(verbosity=2)
