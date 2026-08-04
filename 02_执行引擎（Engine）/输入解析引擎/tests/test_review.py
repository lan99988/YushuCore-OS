"""
tests/test_review.py

验证 handlers/review.py 与旧输入解析引擎（input_parser / router 桥）的 1:1 行为一致性。

原则：
- review 是查询型 Handler，仅调用 _run_lark_cli 的读操作（无 insert / 无 runtime 写），
  全部 monkeypatch 注入假数据，不触碰真实 Feishu / Lark 网络。
- 统计依赖 datetime.now() 计算回顾窗口，必须冻结 now 使新旧两侧窗口一致、报告日期字符串逐字相等。
  （注意：datetime.datetime.now 是 C 级不可变方法，无法 patch.object 类属性；
   故改为 patch 模块级全局名 datetime，并保留 strptime 真实逻辑。）
- parity：同时 patch review.* 与 legacy.* 双副本，端到端新旧 dict 相等（零网络）。
- 旧 router._call_review 桥逻辑（days 解析 + 「深度」判断）已并入 review.handle_review，
  故 entrypoint parity 用测试中重建的旧桥行为作基准。
"""

import os
import sys
import json
import datetime as _dt_module
import unittest
import unittest.mock as mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import review


# 冻结 now，使回顾窗口在旧/新两侧完全一致；报告中的「mm/dd - mm/dd」也逐字相等。
FROZEN_NOW = _dt_module.datetime(2026, 7, 25, 12, 0, 0)


def _make_fake_datetime():
    """替换模块级全局 datetime：now 返回固定值，strptime 保留真实解析逻辑。"""
    fd = mock.MagicMock()
    fd.now.return_value = FROZEN_NOW
    fd.strptime.side_effect = lambda s, fmt: _dt_module.datetime.strptime(s, fmt)
    return fd


# 执行库假数据：TaskA/TaskB 在窗口内，TaskC 在窗口外（验证创建时间过滤）。
NORMAL_STDOUT = json.dumps({
    "data": {
        "fields": ["标题", "状态", "创建时间", "所属项目", "科目类别", "轻重缓急", "预估耗时"],
        "data": [
            ["任务A", "已完成", "2026-07-22T10:00:00", "考研", "数学", "P1", 120],
            ["任务B", "进行中", "2026-07-21T09:00:00", "日常", "", "P2", 60],
            ["任务C", "已完成", "2026-06-01T09:00:00", "旧项目", "", "P3", 30],
        ],
    }
})

# 深度工作表假数据：07-22 / 07-20 在窗口内，06-01 在窗口外。
DEEP_STDOUT = json.dumps({
    "data": {
        "fields": ["日期", "当日深度工作时长(min)", "干扰次数", "最高心流状态"],
        "data": [
            ["2026/07/22", "180", "1", "高"],
            ["2026/07/20", "120", "5", "低"],
            ["2026/06/01", "90", "0", "巅峰"],
        ],
    }
})


class _FakeResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _fake_cli_factory(normal_json, deep_json):
    """根据 args 中的 --table-id 决定返回执行库（普通复盘）还是深度工作表（深度复盘）。"""
    deep_id = review.DEEP_WORK_TABLE_ID

    def _fake(args_list, json_input=None):
        if args_list and deep_id in args_list:
            return _FakeResult(0, deep_json)
        return _FakeResult(0, normal_json)

    return _fake


class TestRoute(unittest.TestCase):
    def test_route_key(self):
        self.assertEqual(router._resolve_route_key("#复盘 7")[0], "review")
        self.assertEqual(router._resolve_route_key("#复盘深度 7")[0], "review")

    def test_resolve_prefers_review_prefix(self):
        # 「复盘深度」仍以 #复盘 开头 -> review 路由（深度分支在 handler 内分流）
        self.assertEqual(router._resolve_route_key("#复盘深度 7")[0], "review")


class TestDispatch(unittest.TestCase):
    def test_normal_dispatch_returns_review(self):
        fake = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake):
            res = review.handle_review("#复盘 7")
        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "review")
        # 窗口内 2 条、窗口外 1 条 -> 完成率 50%
        self.assertEqual(res["stats"]["total"], 2)
        self.assertEqual(res["stats"]["completed"], 1)
        self.assertEqual(res["stats"]["completion_rate"], 50.0)

    def test_deep_dispatch_returns_deep_review(self):
        fake = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake):
            res = review.handle_review("#复盘 深度 7")
        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "deep_review")
        self.assertEqual(res["stats"]["days"], 2)
        self.assertEqual(res["stats"]["total_deep_minutes"], 300)
        self.assertEqual(res["stats"]["flow_days"], 1)

    def test_days_parsing_normal(self):
        fake = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake):
            res = review.handle_review("#复盘 14")
        # 标题含解析出的天数
        self.assertIn("【14天复盘报告】", res["message"])

    def test_days_parsing_forward_to_deep(self):
        captured = {}
        orig = review._handle_deep_review

        def _spy(days, dry_run=False):
            captured["days"] = days
            return orig(days, dry_run=dry_run)

        fake = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        # 注意：days 解析正则 #复盘\s+(\d+) 要求数字紧跟 #复盘 之后，
        # 「深度」必须放在天数之后（#复盘 14 深度）才能解析到 14；
        # 这是旧 _call_review 桥的既有行为，搬家不装修，原样保留。
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(review, "_handle_deep_review", side_effect=_spy):
            review.handle_review("#复盘 14 深度")
        self.assertEqual(captured["days"], 14)


class TestParityVsLegacy(unittest.TestCase):
    def _old_bridge(self, text, dry_run):
        """重建旧 router._call_review 桥行为，作为 entrypoint parity 基准。"""
        legacy = router._get_legacy()
        days = 7
        m = legacy.re.search(r'#复盘\s+(\d+)', text)
        if m:
            days = int(m.group(1))
        if "深度" in text:
            return legacy.handle_deep_review(days, dry_run=dry_run)
        return legacy.handle_review(days, dry_run=dry_run)

    def _run_entrypoint(self, text, dry_run):
        legacy = router._get_legacy()
        fake_new = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        fake_old = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(legacy, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake_new), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake_old):
            new_res = review.handle_review(text, dry_run=dry_run)
            old_res = self._old_bridge(text, dry_run=dry_run)
        return new_res, old_res

    def test_parity_entrypoint_normal(self):
        new_res, old_res = self._run_entrypoint("#复盘 7", False)
        self.assertEqual(new_res, old_res)

    def test_parity_entrypoint_deep(self):
        new_res, old_res = self._run_entrypoint("#复盘 深度 7", False)
        self.assertEqual(new_res, old_res)

    def test_parity_entrypoint_normal_dry_run(self):
        new_res, old_res = self._run_entrypoint("#复盘 7", True)
        self.assertEqual(new_res, old_res)

    def test_parity_entrypoint_deep_dry_run(self):
        new_res, old_res = self._run_entrypoint("#复盘 深度 7", True)
        self.assertEqual(new_res, old_res)

    def test_parity_internal_normal(self):
        legacy = router._get_legacy()
        fake_new = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        fake_old = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(legacy, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake_new), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake_old):
            new_res = review._handle_review(7)
            old_res = legacy.handle_review(7)
        self.assertEqual(new_res, old_res)

    def test_parity_internal_deep(self):
        legacy = router._get_legacy()
        fake_new = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        fake_old = _fake_cli_factory(NORMAL_STDOUT, DEEP_STDOUT)
        with mock.patch.object(review, "datetime", _make_fake_datetime()), \
             mock.patch.object(legacy, "datetime", _make_fake_datetime()), \
             mock.patch.object(review, "_run_lark_cli", side_effect=fake_new), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake_old):
            new_res = review._handle_deep_review(7)
            old_res = legacy.handle_deep_review(7)
        self.assertEqual(new_res, old_res)

    def test_parity_internal_deep_failure_path(self):
        """深度表读取失败（returncode != 0）时，旧实现返回 ok:True 的特殊消息，必须保留。"""
        legacy = router._get_legacy()

        def _fail_new(args_list, json_input=None):
            return _FakeResult(1, "")

        def _fail_old(args_list, json_input=None):
            return _FakeResult(1, "")

        with mock.patch.object(review, "_run_lark_cli", side_effect=_fail_new), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=_fail_old):
            new_res = review._handle_deep_review(7)
            old_res = legacy.handle_deep_review(7)
        self.assertEqual(new_res, old_res)
        self.assertEqual(new_res["ok"], True)
        self.assertIn("深度工作追踪表暂未创建", new_res["message"])


class TestCutSignal(unittest.TestCase):
    def test_no_legacy_bridge_reference(self):
        with open(router.__file__, encoding="utf-8") as f:
            router_src = f.read()
        self.assertNotIn("_call_review", router_src)

    def test_route_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["review"],
            review.handle_review,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
