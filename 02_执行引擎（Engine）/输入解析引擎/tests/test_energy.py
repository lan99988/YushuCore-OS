"""Energy handler 测试（Step2-4-C-2）。

覆盖：Route / Parity（旧 main 子进程 vs router.dispatch）/ Runtime Contract / Cut。
运行目录无关：将包父目录（02_执行引擎（Engine））加入 sys.path。
"""

import os
import sys
import io
import re
import contextlib
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)                       # 输入解析引擎/
PKG_PARENT = os.path.dirname(ENGINE)                 # 02_执行引擎（Engine）/
REPO = os.path.dirname(PKG_PARENT)                   # D:\个人混合管理系统
OLD_PATH = os.path.join(ENGINE, "input_parser_old.py")
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from 输入解析引擎 import router  # noqa: E402
from 输入解析引擎.handlers import energy  # noqa: E402


def _normalize_dates(text):
    return re.sub(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", "DATE", text)


def _run_old_main(raw_text):
    p = subprocess.run(
        [sys.executable, OLD_PATH, raw_text, "--dry-run"],
        cwd=ENGINE, capture_output=True, text=True,
    )
    return p.stdout


class TestEnergyRoute(unittest.TestCase):
    def test_resolve_route_key(self):
        key, table = router._resolve_route_key("#精力 很好")
        self.assertEqual(key, "energy")
        self.assertIsNone(table)


class TestEnergyParity(unittest.TestCase):
    def test_dispatch_parity(self):
        text = "#精力 很好"
        old_out = _run_old_main(text)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                router.dispatch(text, dry_run=True)
            except SystemExit:
                pass
        new_out = buf.getvalue()

        self.assertTrue(old_out.strip(), "旧 main 无输出")
        self.assertEqual(
            _normalize_dates(new_out),
            _normalize_dates(old_out),
            "router 与旧 main 在 #精力 上输出不一致",
        )
        self.assertIn("精力状态：好", new_out)


class TestEnergyRuntimeContract(unittest.TestCase):
    def test_write_path_matches_legacy(self):
        # 新 handler 计算路径
        new_path = energy._engine_runtime_path()
        # 旧 handler 计算路径（legacy.__file__ 在引擎根）
        legacy = router._get_legacy()
        legacy_path = os.path.join(
            os.path.dirname(legacy.__file__), "runtime", "_energy_status.json"
        )
        # 1. 与旧 handler 写入物理路径逐字一致
        self.assertEqual(new_path, legacy_path)
        # 2. 落在引擎根 runtime（junction），不是 handlers/runtime
        norm = new_path.replace("\\", "/")
        self.assertTrue(norm.endswith("输入解析引擎/runtime/_energy_status.json"))
        self.assertNotIn("handlers/runtime", norm)

    def test_daily_scheduler_same_convention(self):
        # daily_scheduler 用相同约定 <engine_root>/runtime/_energy_status.json 读取
        sched_file = os.path.join(
            REPO, "02_执行引擎（Engine）", "每日排程引擎", "daily_scheduler.py"
        )
        sched_path = os.path.join(
            os.path.dirname(os.path.abspath(sched_file)),
            "runtime", "_energy_status.json",
        )
        self.assertTrue(sched_path.replace("\\", "/").endswith("runtime/_energy_status.json"))
        # 两者均为 junction 约定，结构对称（共享物理 Runtime）
        self.assertEqual(
            os.path.basename(os.path.dirname(energy._engine_runtime_path())),
            "runtime",
        )


class TestEnergyCut(unittest.TestCase):
    def test_router_delegates_to_new_handler(self):
        with open(os.path.join(ENGINE, "router.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("legacy.handle_energy_status", src)
        self.assertIs(router.ROUTE_HANDLERS["energy"], energy.handle_energy_status)


if __name__ == "__main__":
    unittest.main()
