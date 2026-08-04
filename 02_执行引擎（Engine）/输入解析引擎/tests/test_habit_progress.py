"""C-9c habit_progress 迁移测试。

验证 handlers/habit_progress.py 与旧 handle_habit_progress(1964-2041) 的 1:1 行为一致性。
查询型 handler：飞书读习惯数据 → 本地格式统计展示，无写入、无 runtime。
覆盖：路由键 / true cut / 空内容→help / 查不到→error / 获取失败→error / 成功展示 / 建议逻辑 / parity。
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
from 输入解析引擎.handlers import habit_progress


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr or ""


_SAMPLE_FIELDS = [
    "习惯名称", "身份声明", "执行意图", "习惯叠加",
    "提示位置", "频率", "当前连续天数", "历史最佳", "总打卡次数",
]
_SAMPLE_ROW = [
    "背单词", "背词者", "早饭后在书桌前", "刷牙之后",
    "单词本放桌面", "每天", 7, 14, 42,
]


class TestHabitProgressRoute(unittest.TestCase):
    def test_route_key(self):
        """#习惯进度 前缀路由到 habit_progress"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#习惯进度 背单词")
        self.assertEqual(key, "habit_progress")

    def test_route_key_empty(self):
        """#习惯进度 无内容仍路由正确"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#习惯进度")
        self.assertEqual(key, "habit_progress")

    def test_route_key_not_habit(self):
        """#习惯 不冲突 #习惯进度（长前缀优先）"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#习惯 每天背单词")
        self.assertEqual(key, "habit")


class TestHabitProgressCutSignal(unittest.TestCase):
    def test_call_bridge_removed(self):
        """router 无 _call_habit_progress"""
        self.assertFalse(hasattr(router, "_call_habit_progress"))

    def test_route_handlers_points_to_new(self):
        """ROUTE_HANDLERS['habit_progress'] 是新 handler"""
        self.assertIs(
            router.ROUTE_HANDLERS["habit_progress"],
            habit_progress.handle_habit_progress,
        )


class TestHabitProgressBehavior(unittest.TestCase):
    def test_empty_content(self):
        """空内容 → habit_error 提示"""
        res = habit_progress.handle_habit_progress("#习惯进度", dry_run=True)
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("请指定习惯名", res["message"])

    def test_no_match(self):
        """未找到匹配习惯 → habit_error"""
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [_SAMPLE_ROW]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 不存在的习惯")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("未找到习惯", res["error"])

    def test_fetch_failure(self):
        """飞书返回非零 → habit_error"""
        r = _FakeResult(1, "", "read error")
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(res["type"], "habit_error")
        self.assertIn("读取习惯表失败", res["error"])

    def test_exception(self):
        """异常 → habit_error"""
        with mock.patch.object(
            habit_progress, "_run_lark_cli",
            side_effect=Exception("网络错误"),
        ):
            res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(res["type"], "habit_error")
        self.assertEqual(res["error"], "网络错误")

    def test_success_all_fields(self):
        """全字段习惯 → 消息含所有信息"""
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [_SAMPLE_ROW]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(res["type"], "habit_progress")
        self.assertTrue(res["ok"])
        msg = res["message"]
        self.assertIn("背单词", msg)
        self.assertIn("背词者", msg)
        self.assertIn("早饭后在书桌前", msg)
        self.assertIn("刷牙之后", msg)
        self.assertIn("单词本放桌面", msg)
        self.assertIn("连续7天", msg)
        self.assertIn("最佳14天", msg)
        self.assertIn("总计42次", msg)

    def test_success_partial_fields(self):
        """部分字段 → 只显示有值的"""
        row = ["晨跑", "", "", "", "", "每天", 0, 0, 0]
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 晨跑")
        self.assertEqual(res["type"], "habit_progress")
        self.assertNotIn("身份：", res["message"])
        self.assertNotIn("执行意图：", res["message"])

    def test_streak_7_plus_no_streak_suggestion(self):
        """连续≥7天 → 自动化建议（含）, 连续0原始0 → 两分钟建议"""
        row = ["阅读", "读者", "", "", "", "每天", 7, 7, 10]
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 阅读")
        msg = res["message"]
        self.assertIn("开始自动化", msg)
        self.assertNotIn("两分钟规则", msg)

    def test_streak_zero_total_zero_two_minute_suggestion(self):
        """连续0且总计0 → 两分钟建议"""
        row = ["冥想", "", "", "", "", "每天", 0, 0, 0]
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 冥想")
        msg = res["message"]
        self.assertIn("两分钟规则", msg)
        self.assertNotIn("开始自动化", msg)

    def test_missing_fields_suggestions(self):
        """无身份/无意图/无提示 → 对应建议"""
        row = ["写作", "", "", "", "", "每天", 3, 5, 20]
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 写作")
        msg = res["message"]
        self.assertIn("缺乏身份声明", msg)
        self.assertIn("没有执行意图", msg)
        self.assertIn("没有环境提示", msg)

    def test_dry_run_parameter(self):
        """dry_run 形参被接受（旧逻辑忽略，但不崩溃）"""
        res = habit_progress.handle_habit_progress("", dry_run=True)
        self.assertEqual(res["type"], "habit_error")

    def test_partial_name_match(self):
        """局部匹配（content in 习惯名称）"""
        row = ["每天背单词", "背词者", "", "", "", "每天", 5, 10, 30]
        fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, fake_stdout)
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(res["type"], "habit_progress")
        self.assertIn("每天背单词", res["message"])


class TestHabitProgressParity(unittest.TestCase):
    """新旧 handler 对相同输入返回一致结果（mock 飞书读取）"""

    def setUp(self):
        self.fake_stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [_SAMPLE_ROW]}
        })
        self.r = _FakeResult(0, self.fake_stdout)

    def _get_new(self, text):
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=self.r):
            return habit_progress.handle_habit_progress(text)

    def _get_old(self, text):
        old = router._get_legacy()
        with mock.patch.object(old, "_run_lark_cli", return_value=self.r):
            return old.handle_habit_progress(text)

    def assert_progress_equal(self, text):
        old_res = self._get_old(text)
        new_res = self._get_new(text)
        self.assertEqual(old_res, new_res)

    def test_parity_basic_query(self):
        """#习惯进度 背单词 新旧一致"""
        self.assert_progress_equal("#习惯进度 背单词")

    def test_parity_empty(self):
        """#习惯进度（空） 新旧一致"""
        self.assert_progress_equal("#习惯进度")

    def test_parity_no_match(self):
        """#习惯进度 不存在的习惯 新旧一致"""
        self.assert_progress_equal("#习惯进度 不存在的习惯")

    def test_parity_fetch_fail(self):
        """读取失败 新旧一致"""
        r_fail = _FakeResult(1, "", "error")
        old = router._get_legacy()
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r_fail):
            new_res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        with mock.patch.object(old, "_run_lark_cli", return_value=r_fail):
            old_res = old.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(old_res, new_res)

    def test_parity_partial_fields(self):
        """部分字段习惯 新旧一致"""
        row = ["晨跑", "", "", "", "", "每天", 0, 0, 0]
        stdout = json.dumps({
            "data": {"fields": _SAMPLE_FIELDS, "data": [row]}
        })
        r = _FakeResult(0, stdout)
        old = router._get_legacy()
        with mock.patch.object(habit_progress, "_run_lark_cli", return_value=r):
            new_res = habit_progress.handle_habit_progress("#习惯进度 晨跑")
        with mock.patch.object(old, "_run_lark_cli", return_value=r):
            old_res = old.handle_habit_progress("#习惯进度 晨跑")
        self.assertEqual(old_res, new_res)

    def test_parity_exception(self):
        """异常情况 新旧一致"""
        old = router._get_legacy()
        with mock.patch.object(
            habit_progress, "_run_lark_cli",
            side_effect=Exception("网络错误"),
        ):
            new_res = habit_progress.handle_habit_progress("#习惯进度 背单词")
        with mock.patch.object(
            old, "_run_lark_cli",
            side_effect=Exception("网络错误"),
        ):
            old_res = old.handle_habit_progress("#习惯进度 背单词")
        self.assertEqual(old_res, new_res)


if __name__ == "__main__":
    unittest.main()
