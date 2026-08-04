"""
router 单元测试（Step2-4-A）

覆盖：
- 路由键解析（_resolve_route_key）：所有前缀 -> 正确路由键。
- #任务：router.dispatch 输出 与 旧 main() 端到端完全一致（dry-run，无网络）。
- #精力：同上（handle_energy_status 仅写本地 json，无网络）。
- #比赛：路由到 competition 处理函数（mock，验证分发正确性，避免真实网络）。
- 未知前缀：输出「无法识别」并 sys.exit(1)。

运行：
    python tests/test_router.py -v
    python -m unittest tests.test_router -v
"""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

# 把引擎父目录加入 sys.path，使 `输入解析引擎` 成为可导入包
HERE = os.path.dirname(os.path.abspath(__file__))          # .../tests
ENGINE = os.path.dirname(HERE)                             # .../输入解析引擎
ENGINE_PARENT = os.path.dirname(ENGINE)                    # .../02_执行引擎（Engine）
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router  # noqa: E402


def _capture_stdout(func, *args, **kwargs):
    """捕获 func 的 stdout。

    关键：不 mock sys.exit，而是捕获其抛出的 SystemExit（旧 main 靠 sys.exit
    在各分支终点 halt，mock 会让它穿透到标准路径，造成虚假差异）。输出在 exit
    前已打印，捕获后与正常返回等价。
    """
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            func(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


class RouteKeyTest(unittest.TestCase):
    """_resolve_route_key：前缀 -> 路由键（标准路径为 None）。"""

    CASES = {
        # 标准路径（走 build_record 通用流程）
        "#任务 做数学真题": None,
        "#灵感 想到一个方法": None,
        "#Bug 页面崩溃": None,
        "#账单 午饭 28元 餐饮": None,
        "#社交 见了张三 同学": None,
        "#创作 公众号文章": None,
        "#知识 泰勒公式": None,
        # 特殊指令
        "#临时 买牛奶": "lightweight",
        "#精力 今天状态很差": "energy",
        "#配置 黄金段 08:30-11:30": "config_cmd",
        "#孵化 一个想法": "hatch",
        "#复盘": "review",
        "#复盘 14": "review",
        "#复盘深度": "review",
        "#排程到日历": "schedule_calendar",
        "#日历": "schedule_calendar",
        "#深度规划 x": "deep_plan",
        "#深度记录 x": "deep_record",
        "#深度 x": "deep_work",
        "#注意力审计 x": "attention_audit",
        "#习惯打卡 x": "habit_checkin",
        "#习惯进度 x": "habit_progress",
        "#习惯 x": "habit",
        "#比赛 列表": "competition",
        "#同步任务框": "sync_taskbox",
        "#身体 今天适合练什么": "body_os",
        "#训练 卧推 5x5": "body_os",
        "#营养 蛋白质 120g": "body_os",
        "#恢复 今天很酸": "body_os",
        "#体测 体重 70kg": "body_os",
        # 无法识别
        "#乱码xyz": "unknown",
    }

    def test_resolve_route_keys(self):
        for text, expected in self.CASES.items():
            with self.subTest(text=text):
                key, _ = router._resolve_route_key(text)
                self.assertEqual(key, expected, msg=f"前缀路由错误：{text}")


class DispatchParityTest(unittest.TestCase):
    """router.dispatch 输出与旧 main() 完全等价（搬家不装修的核心验证）。"""

    def _run_old_main(self, text):
        legacy = router._get_legacy()
        sys.argv = ["input_parser.py", text, "--dry-run"]
        return _capture_stdout(legacy.main)

    def _run_router(self, text):
        return _capture_stdout(router.dispatch, text, True)

    def test_dispatch_task_parity(self):
        text = "#任务 做数学真题2010 【项目：数学二】【精力：高】【耗时：120分钟】"
        old_out = self._run_old_main(text)
        new_out = self._run_router(text)
        self.assertTrue(old_out.strip(), "旧 main 无输出")
        self.assertEqual(new_out, old_out, "router 与旧 main 在 #任务 上输出不一致")

    def test_dispatch_energy_parity(self):
        text = "#精力 今天状态很差"
        old_out = self._run_old_main(text)
        new_out = self._run_router(text)
        self.assertTrue(old_out.strip(), "旧 main 无输出")
        self.assertEqual(new_out, old_out, "router 与旧 main 在 #精力 上输出不一致")
        self.assertIn("精力状态：差", new_out)


class CompetitionRouteTest(unittest.TestCase):
    """#比赛 应路由到 competition 处理函数（mock 避免真实网络）。"""

    def test_dispatch_competition_routes(self):
        fake = {"ok": True, "type": "competition", "message": "<<COMP_RESULT>>"}
        mock_handler = mock.Mock(return_value=fake)

        with mock.patch.dict(router.ROUTE_HANDLERS, {"competition": mock_handler}):
            out = _capture_stdout(router.dispatch, "#比赛 列表", True)

        mock_handler.assert_called_once_with("#比赛 列表", dry_run=True)
        self.assertIn("<<COMP_RESULT>>", out)


class BodyOSRouteTest(unittest.TestCase):
    """Body OS 指令统一路由到 body_os 处理函数。"""

    def test_dispatch_body_os_routes(self):
        fake = {"ok": True, "type": "body_os", "message": "<<BODY_OS_RESULT>>"}
        mock_handler = mock.Mock(return_value=fake)

        with mock.patch.dict(router.ROUTE_HANDLERS, {"body_os": mock_handler}):
            out = _capture_stdout(router.dispatch, "#身体 今天适合练什么", True)

        mock_handler.assert_called_once_with("#身体 今天适合练什么", dry_run=True)
        self.assertIn("<<BODY_OS_RESULT>>", out)


class UnknownPrefixTest(unittest.TestCase):
    """未知前缀：提示无法识别并 sys.exit(1)。"""

    def test_unknown_prefix_exits(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(buf):
            router.dispatch("#乱码测试 内容", dry_run=True)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("无法识别", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
