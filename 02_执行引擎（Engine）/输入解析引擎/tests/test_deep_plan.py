"""C-8a deep_plan 迁移测试。

验证 handlers/deep_plan.py 与旧 handle_deep_plan(1363-1416) 的 1:1 行为一致性。
覆盖：路由键 / true cut 信号 / runtime 路径保护 / 真实写入 / parity。
"""

import os
import sys
import json
import tempfile
import unittest
import unittest.mock as mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import deep_plan

import datetime as _real_dt


class _FakeNow:
    def strftime(self, fmt):
        return "2026-07-26 11:00"


class _FakeDateTime:
    @staticmethod
    def now():
        return _FakeNow()

    @staticmethod
    def strptime(s, f):
        return _real_dt.datetime.strptime(s, f)


class TestDeepPlanRoute(unittest.TestCase):
    def test_route_key(self):
        self.assertEqual(
            router._resolve_route_key("#深度规划 深度4小时 浮浅控制30%")[0],
            "deep_plan",
        )
        self.assertEqual(
            router._resolve_route_key("#深度规划 深度3h 浮浅1h")[0],
            "deep_plan",
        )


class TestDeepPlanCut(unittest.TestCase):
    def test_bridge_removed(self):
        self.assertFalse(
            hasattr(router, "_call_deep_plan"),
            "legacy _call_deep_plan bridge still present in router",
        )

    def test_map_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["deep_plan"],
            deep_plan.handle_deep_plan,
        )


class TestDeepPlanRuntimePath(unittest.TestCase):
    def test_runtime_path_no_handlers_segment(self):
        p = deep_plan._engine_runtime_path()
        self.assertTrue(p.endswith(os.path.join("runtime", "_deep_work_plan.json")))
        # 关键路径保护：不得落到 handlers/runtime（非 junction，排程引擎读不到）
        self.assertNotIn("handlers", p)

    def test_writes_to_runtime(self):
        tmp = tempfile.mkdtemp()
        fake = os.path.join(tmp, "runtime", "_deep_work_plan.json")
        os.makedirs(os.path.dirname(fake), exist_ok=True)
        orig = deep_plan._engine_runtime_path
        deep_plan._engine_runtime_path = lambda: fake
        try:
            res = deep_plan.handle_deep_plan("#深度规划 深度4小时 浮浅控制30%")
            self.assertTrue(os.path.exists(fake))
            with open(fake, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["deep_work_hours_target"], 4.0)
            self.assertEqual(data["shallow_work_budget_pct"], 30)
            self.assertEqual(res["type"], "deep_plan")
        finally:
            deep_plan._engine_runtime_path = orig


class TestDeepPlanParity(unittest.TestCase):
    def _run_pair(self, text):
        legacy = router._get_legacy()
        with mock.patch.object(deep_plan, "datetime", _FakeDateTime), \
             mock.patch.object(legacy, "datetime", _FakeDateTime), \
             mock.patch("builtins.open", mock.mock_open()):
            old = legacy.handle_deep_plan(text)
            new = deep_plan.handle_deep_plan(text)
        return old, new

    def test_parity_basic(self):
        old, new = self._run_pair("#深度规划 深度4小时 浮浅控制30%")
        self.assertEqual(old["ok"], new["ok"])
        self.assertEqual(old["type"], new["type"])
        self.assertEqual(old["message"], new["message"])
        self.assertEqual(old["plan"], new["plan"])

    def test_parity_default_shallow(self):
        old, new = self._run_pair("#深度规划 深度3小时")
        self.assertEqual(new["plan"]["deep_work_hours_target"], 3.0)
        self.assertEqual(new["plan"]["shallow_work_budget_pct"], 30)
        self.assertEqual(old["plan"], new["plan"])

    def test_parity_shallow_hours_recompute(self):
        old, new = self._run_pair("#深度规划 深度4h 浮浅2h")
        # 4h 深度 + 2h 浮浅 = 6h → 浮浅占比 33%
        self.assertEqual(new["plan"]["shallow_work_budget_pct"], 33)
        self.assertEqual(old["plan"], new["plan"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
