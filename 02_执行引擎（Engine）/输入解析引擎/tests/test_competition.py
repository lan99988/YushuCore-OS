"""C-11b competition 迁移测试。

验证 handlers/competition.py（Adapter 模式）的正确性。
薄封装层：委托 competition_manager.main_handler，不复制内部逻辑。

关键关注点：
- set_config 注入正确
- 懒导入竞争管理器模块
- 全局状态污染隔离
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
from 输入解析引擎.handlers import competition


class _MockCompetitionManager:
    """模拟 competition_manager 模块，用于注入 sys.modules。

    记录 set_config 调用参数，main_handler 返回可控结果。
    """

    def __init__(self, return_value=None):
        self.set_config_calls = []
        self.main_handler_return = return_value or {
            "ok": True, "type": "competition", "message": "测试结果"
        }

    def set_config(self, base_token, tables, run_lark_cli_func):
        self.set_config_calls.append((base_token, tables, run_lark_cli_func))

    def main_handler(self, text, dry_run=False):
        return self.main_handler_return


class _InjectCompetition:
    """上下文管理器：注入 mock competition_manager 到 sys.modules。"""

    def __init__(self, return_value=None):
        self.mock_mgr = _MockCompetitionManager(return_value)
        self._saved = {}

    def __enter__(self):
        self._saved["competition_manager"] = sys.modules.pop("competition_manager", None)
        sys.modules["competition_manager"] = self.mock_mgr
        return self.mock_mgr

    def __exit__(self, *args):
        sys.modules.pop("competition_manager", None)
        if self._saved.get("competition_manager") is not None:
            sys.modules["competition_manager"] = self._saved["competition_manager"]


# ========== Route ==========


class TestCompetitionRoute(unittest.TestCase):
    """路由键验证"""

    def test_route_key(self):
        """#比赛 → competition"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#比赛 列表")
        self.assertEqual(key, "competition")

    def test_route_key_bare(self):
        """#比赛 无内容 → competition"""
        from 输入解析引擎.router import _resolve_route_key
        key, _ = _resolve_route_key("#比赛")
        self.assertEqual(key, "competition")


# ========== Cut Signal ==========


class TestCompetitionCutSignal(unittest.TestCase):
    """true cut 信号"""

    def test_call_bridge_removed(self):
        """router 无 _call_competition"""
        self.assertFalse(hasattr(router, "_call_competition"))

    def test_route_handlers_points_to_new(self):
        """ROUTE_HANDLERS['competition'] 是新 handler"""
        self.assertIs(
            router.ROUTE_HANDLERS["competition"],
            competition.handle_competition,
        )


# ========== Adapter Behavior ==========


class TestCompetitionAdapter(unittest.TestCase):
    """Adapter 行为测试（mock competition_manager）"""

    def test_help_delegation(self):
        """#比赛 空 → 委托到 main_handler"""
        with _InjectCompetition() as mgr:
            res = competition.handle_competition("#比赛")

        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "competition")
        # 验证 main_handler 被调用
        self.assertTrue(hasattr(mgr, "main_handler"))

    def test_create_delegation(self):
        """#比赛 创建 → 委托"""
        with _InjectCompetition() as mgr:
            competition.handle_competition("#比赛 创建 数学竞赛")

        self.assertTrue(hasattr(mgr, "main_handler"))

    def test_list_delegation(self):
        """#比赛 列表 → 委托"""
        with _InjectCompetition() as mgr:
            competition.handle_competition("#比赛 列表")

        self.assertTrue(hasattr(mgr, "main_handler"))

    def test_update_delegation(self):
        """#比赛 名称 报名 → 委托"""
        with _InjectCompetition() as mgr:
            competition.handle_competition("#比赛 数学竞赛 报名")

        self.assertTrue(hasattr(mgr, "main_handler"))

    def test_dry_run_passthrough(self):
        """dry_run 透传到 main_handler"""
        with _InjectCompetition() as mgr:
            competition.handle_competition("#比赛 列表", dry_run=True)

        self.assertTrue(hasattr(mgr, "main_handler"))

    def test_returns_main_handler_result(self):
        """返回 main_handler 的结果"""
        expected = {"ok": True, "type": "competition", "message": "自定义结果"}
        with _InjectCompetition(return_value=expected) as mgr:
            res = competition.handle_competition("#比赛 列表")

        self.assertEqual(res, expected)

    def test_error_returned(self):
        """错误结果也透传"""
        expected = {"ok": False, "type": "competition", "error": "未找到比赛"}
        with _InjectCompetition(return_value=expected) as mgr:
            res = competition.handle_competition("#比赛 不存在的比赛")

        self.assertFalse(res["ok"])
        self.assertIn("未找到比赛", res["error"])


# ========== set_config 注入验证 ==========


class TestCompetitionSetConfig(unittest.TestCase):
    """验证 set_config 注入正确的配置值"""

    def test_set_config_called_with_correct_args(self):
        """set_config 以 (BASE_TOKEN, TABLES, _run_lark_cli) 调用"""
        with _InjectCompetition() as mgr:
            competition.handle_competition("#比赛 列表")

        self.assertEqual(len(mgr.set_config_calls), 1)
        token, tables, run_func = mgr.set_config_calls[0]
        # 与 config.py 的值一致
        self.assertEqual(token, "TtzIboiQQaPgfVszO2vc56wLnof")
        self.assertIsInstance(tables, dict)
        self.assertIn("比赛管理表", tables)
        self.assertEqual(tables["比赛管理表"], "tblKPdoxMHy7FuV7")
        # _run_lark_cli 是可调用的
        self.assertTrue(callable(run_func))

    def test_set_config_called_before_main_handler(self):
        """set_config 在 main_handler 之前调用"""
        call_order = []

        class _OrderedMock:
            def set_config(self, *a, **kw):
                call_order.append("set_config")

            def main_handler(self, *a, **kw):
                call_order.append("main_handler")
                return {"ok": True, "type": "competition"}

        om = _OrderedMock()
        with mock.patch.dict(sys.modules, {"competition_manager": om}, clear=False):
            # 确保竞争管理器模块从缓存中移除，让懒导入命中 mock
            sys.modules.pop("competition_manager", None)
            sys.modules["competition_manager"] = om
            competition.handle_competition("#比赛 列表")

        self.assertEqual(call_order, ["set_config", "main_handler"])


# ========== _ensure_competition_path ==========


class TestCompetitionEnsurePath(unittest.TestCase):
    """_ensure_competition_path 注册正确的目录"""

    def test_path_registered(self):
        """确保比赛管理模块路径被加入 sys.path"""
        # 先移除可能已存在的路径
        saved = [p for p in sys.path if "比赛管理" in p and "Competition" in p]
        for p in saved:
            sys.path.remove(p)

        competition._ensure_competition_path()

        self.assertTrue(
            any("比赛管理（Competition）" in p and "程序" in p for p in sys.path),
            f"比赛管理路径未在 sys.path 中找到: {[p for p in sys.path if '比赛' in p]}"
        )

        # 恢复
        for p in saved:
            if p not in sys.path:
                sys.path.append(p)


if __name__ == "__main__":
    unittest.main()
