"""
Step2-4-C-1 测试：lightweight handler 迁移验证

覆盖：
1. 路由解析：#临时 -> ("lightweight", None)
2. 真实入口 parity：router.dispatch(dry_run=True) vs 冻结旧 main 子进程（--dry-run）
3. handler 返回结构
4. cut 信号：router 不再委托 legacy.handle_lightweight_task，ROUTE_HANDLERS 直指新 handler

pytest 未安装，使用标准 unittest（与项目其他测试一致）。
"""

import io
import os
import sys
import contextlib
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)                       # 02_执行引擎（Engine）/输入解析引擎
OLD_PATH = os.path.join(ENGINE, "input_parser_old.py")
PARENT = os.path.dirname(ENGINE)                     # 02_执行引擎（Engine）
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from 输入解析引擎 import router                      # noqa: E402
from 输入解析引擎.handlers import lightweight        # noqa: E402

# 确定性输入：带显式截止日期 -> due_ms 由 strptime 算出，无 now() 漂移 -> parity 可逐字节一致
LW_INPUT = "#临时 交报告 【项目：项目A】【截止：2026/07/20】"


def _old_main_output(text):
    """运行冻结旧 main（--dry-run），返回 stdout。"""
    proc = subprocess.run(
        [sys.executable, OLD_PATH, text, "--dry-run"],
        cwd=ENGINE, capture_output=True, text=True, timeout=60,
    )
    return proc.stdout


class TestLightweight(unittest.TestCase):

    def test_resolve_route_key(self):
        key, table = router._resolve_route_key("#临时 买牛奶")
        self.assertEqual(key, "lightweight")
        self.assertIsNone(table)

    def test_dispatch_parity(self):
        old_out = _old_main_output(LW_INPUT)
        self.assertTrue(old_out.strip(), "旧 main 无输出")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                router.dispatch(LW_INPUT, dry_run=True)
        new_out = buf.getvalue()

        self.assertEqual(
            new_out.strip(), old_out.strip(),
            "router.dispatch 与旧 main 在 #临时 上输出不一致",
        )

    def test_handler_returns_dict(self):
        result = lightweight.handle_lightweight_task("#临时 买牛奶", dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result.get("type"), "lightweight")
        self.assertIn("标题：[临时] 买牛奶", result.get("message", ""))

    def test_router_delegates_to_new_handler(self):
        # cut 信号 1：router 全文件不再调用遗留 lightweight 业务函数
        with open(os.path.join(ENGINE, "router.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("legacy.handle_lightweight_task", src)
        self.assertIn("lightweight.handle_lightweight_task", src)
        # cut 信号 2：路由表直指新 handler
        self.assertIs(
            router.ROUTE_HANDLERS["lightweight"],
            lightweight.handle_lightweight_task,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
