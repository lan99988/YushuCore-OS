"""
Step2-4-B 验收：standard_record handler 端到端 parity 测试。

验证目标：
  router.dispatch(text, dry_run=True)
      -> _call_standard -> handlers.standard_record.handle_standard_record
      -> builders.build_record -> feishu_write.insert_to_feishu(dry_run)
  输出与冻结的 input_parser_old.main(text, --dry-run) 逐字一致。

覆盖 7 类标准指令：#任务 #灵感 #Bug #账单 #社交 #创作 #知识。

说明：pytest 未安装，使用标准库 unittest。
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
OLD_PATH = os.path.join(ENGINE, "input_parser_old.py")
# 包父目录：.../02_执行引擎（Engine）/（输入解析引擎 包所在层）
PKG_PARENT = os.path.dirname(ENGINE)
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from 输入解析引擎 import router  # noqa: E402

# 日期归一化：新旧两端同一时刻运行，理论上一致；保留以抵御时钟边界。
DATE_RE = re.compile(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}")

STANDARD_CASES = [
    "#任务 写半导体产业链文章",
    "#灵感 AI Agent可能改变个人管理系统",
    "#Bug 健康检查路径错误",
    "#账单 午饭 35元",
    "#社交 张三 讨论AI项目",
    "#创作 半导体文章框架",
    "#知识 光互连产业链研究",
]


def _normalize(text):
    return DATE_RE.sub("DATE", text)


def _run_old(text):
    """通过子进程运行冻结的旧 main，捕获 stdout。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, OLD_PATH, text, "--dry-run"],
        cwd=ENGINE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    return _normalize(proc.stdout), proc.returncode


def _run_new(text):
    """通过新管线 router.dispatch 运行，捕获 stdout。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        router.dispatch(text, dry_run=True)
    return _normalize(buf.getvalue())


class TestStandardRecordStructure(unittest.TestCase):
    """结构检查：确认已真正切断旧 main 标准分支。"""

    def test_handler_importable(self):
        from 输入解析引擎.handlers import standard_record
        self.assertTrue(callable(standard_record.handle_standard_record))

    def test_router_delegates_to_new_handler(self):
        router_path = os.path.join(ENGINE, "router.py")
        with open(router_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("standard_record.handle_standard_record", src)
        # 真正的写入路径（insert_to_feishu）已从 router 切断，改由新 handler 负责。
        # 注：dispatch 的 dry_run 详情块仍用 legacy 函数做展示重算（B-3 范围外，未改动，
        # 且输出与旧 main 一致），故不以 legacy.build_record 作为 cut 信号。
        self.assertNotIn("legacy.insert_to_feishu", src)


class TestStandardRecordParity(unittest.TestCase):
    """输出一致性：新管线 vs 冻结旧 main。"""

    def _assert_parity(self, text):
        old_out, old_rc = _run_old(text)
        new_out = _run_new(text)
        self.assertEqual(old_rc, 0, f"旧 main 异常退出 rc={old_rc}")
        self.assertTrue(old_out.strip(), "旧 main 无输出（用例可能无效）")
        self.assertEqual(
            new_out, old_out,
            f"router→standard_record 与旧 main 在 [{text}] 上输出不一致",
        )

    def test_task_parity(self):
        self._assert_parity(STANDARD_CASES[0])

    def test_idea_parity(self):
        self._assert_parity(STANDARD_CASES[1])

    def test_bug_parity(self):
        self._assert_parity(STANDARD_CASES[2])

    def test_bill_parity(self):
        self._assert_parity(STANDARD_CASES[3])

    def test_social_parity(self):
        self._assert_parity(STANDARD_CASES[4])

    def test_create_parity(self):
        self._assert_parity(STANDARD_CASES[5])

    def test_knowledge_parity(self):
        self._assert_parity(STANDARD_CASES[6])


if __name__ == "__main__":
    unittest.main(verbosity=2)
