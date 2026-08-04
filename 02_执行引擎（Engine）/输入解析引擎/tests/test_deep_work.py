"""C-8c deep_work 迁移测试。

验证 handlers/deep_work.py 与旧 handle_deep_work(1525-1557) 的 1:1 行为一致性。
重点：二级分发 + 零 legacy 依赖（直接调用新 handlers.deep_plan / handlers.deep_record）。
"""

import os
import sys
import unittest
import unittest.mock as mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import deep_work

HANDLERS_DIR = os.path.join(os.path.dirname(HERE), "handlers")
DEEP_WORK_PATH = os.path.join(HANDLERS_DIR, "deep_work.py")

_FAKE_PLAN = {"ok": True, "type": "deep_plan", "message": "P", "plan": {}}
_FAKE_REC = {"ok": True, "type": "deep_record", "message": "R", "record": {}}


class TestDeepWorkRoute(unittest.TestCase):
    def test_route_key_deep(self):
        self.assertEqual(
            router._resolve_route_key("#深度 心流高")[0], "deep_work"
        )

    def test_route_key_plan_via_route(self):
        # #深度规划 直路由到 deep_plan（不经 deep_work）
        self.assertEqual(
            router._resolve_route_key("#深度规划 深度4小时")[0], "deep_plan"
        )

    def test_route_key_record_via_route(self):
        self.assertEqual(
            router._resolve_route_key("#深度记录 今天完成AI研究")[0], "deep_record"
        )


class TestDeepWorkCut(unittest.TestCase):
    def test_bridge_removed(self):
        self.assertFalse(
            hasattr(router, "_call_deep_work"),
            "legacy _call_deep_work bridge still present in router",
        )

    def test_map_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["deep_work"],
            deep_work.handle_deep_work,
        )


class TestDeepWorkDispatch(unittest.TestCase):
    def test_dispatch_to_plan(self):
        with mock.patch.object(deep_work.deep_plan, "handle_deep_plan") as p_plan, \
             mock.patch.object(deep_work.deep_record, "handle_deep_record") as p_rec:
            p_plan.return_value = {"ok": True, "type": "deep_plan", "message": "P", "plan": {}}
            p_rec.return_value = {"ok": True, "type": "deep_record", "message": "R", "record": {}}
            res = deep_work.handle_deep_work("#深度 规划 4小时")
        p_plan.assert_called_once()
        p_rec.assert_not_called()
        self.assertEqual(res["type"], "deep_plan")

    def test_dispatch_to_record_by_keyword(self):
        with mock.patch.object(deep_work.deep_plan, "handle_deep_plan") as p_plan, \
             mock.patch.object(deep_work.deep_record, "handle_deep_record") as p_rec:
            p_plan.return_value = {"ok": True, "type": "deep_plan", "message": "P", "plan": {}}
            p_rec.return_value = {"ok": True, "type": "deep_record", "message": "R", "record": {}}
            res = deep_work.handle_deep_work("#深度 心流高")
        p_rec.assert_called_once()
        p_plan.assert_not_called()
        self.assertEqual(res["type"], "deep_record")

    def test_dispatch_record_by_number(self):
        with mock.patch.object(deep_work.deep_plan, "handle_deep_plan") as p_plan, \
             mock.patch.object(deep_work.deep_record, "handle_deep_record") as p_rec:
            p_plan.return_value = {"ok": True, "type": "deep_plan", "message": "P", "plan": {}}
            p_rec.return_value = {"ok": True, "type": "deep_record", "message": "R", "record": {}}
            res = deep_work.handle_deep_work("#深度 深度4小时")
        p_rec.assert_called_once()
        p_plan.assert_not_called()
        self.assertEqual(res["type"], "deep_record")

    def test_dispatch_deep_info_empty(self):
        with mock.patch.object(deep_work.deep_plan, "handle_deep_plan") as p_plan, \
             mock.patch.object(deep_work.deep_record, "handle_deep_record") as p_rec:
            res = deep_work.handle_deep_work("#深度")
        p_plan.assert_not_called()
        p_rec.assert_not_called()
        self.assertEqual(res["type"], "deep_info")

    def test_dispatch_deep_info_no_keyword(self):
        with mock.patch.object(deep_work.deep_plan, "handle_deep_plan") as p_plan, \
             mock.patch.object(deep_work.deep_record, "handle_deep_record") as p_rec:
            res = deep_work.handle_deep_work("#深度 随便")
        p_plan.assert_not_called()
        p_rec.assert_not_called()
        self.assertEqual(res["type"], "deep_info")


class TestDeepWorkNoLegacy(unittest.TestCase):
    def test_source_has_no_legacy_reference(self):
        with open(DEEP_WORK_PATH, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("input_parser_old", src)
        self.assertNotIn("legacy", src)
        self.assertNotIn("from ..input_parser", src)


class TestDeepWorkParity(unittest.TestCase):
    def _run_pair(self, text):
        legacy = router._get_legacy()
        with mock.patch.object(legacy, "handle_deep_plan", return_value=dict(_FAKE_PLAN)), \
             mock.patch.object(legacy, "handle_deep_record", return_value=dict(_FAKE_REC)), \
             mock.patch.object(deep_work.deep_plan, "handle_deep_plan", return_value=dict(_FAKE_PLAN)), \
             mock.patch.object(deep_work.deep_record, "handle_deep_record", return_value=dict(_FAKE_REC)):
            old = legacy.handle_deep_work(text)
            new = deep_work.handle_deep_work(text)
        return old, new

    def test_parity_deep_info_empty(self):
        old, new = self._run_pair("#深度")
        self.assertEqual(old, new)

    def test_parity_deep_info_no_keyword(self):
        old, new = self._run_pair("#深度 随便")
        self.assertEqual(old, new)

    def test_parity_dispatch_plan(self):
        old, new = self._run_pair("#深度 规划 4小时")
        self.assertEqual(old, new)
        self.assertEqual(old["type"], "deep_plan")

    def test_parity_dispatch_record(self):
        old, new = self._run_pair("#深度 心流高")
        self.assertEqual(old, new)
        self.assertEqual(old["type"], "deep_record")


if __name__ == "__main__":
    unittest.main(verbosity=2)
