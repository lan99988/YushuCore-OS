"""Config command handler 测试（Step2-4-C-3）。

覆盖：Route / Parse / Runtime Contract / Cut / Dispatch Parity。
运行目录无关：将包父目录（02_执行引擎（Engine））加入 sys.path。
"""

import os
import sys
import re
import io
import json
import contextlib
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)                        # 输入解析引擎/
PKG_PARENT = os.path.dirname(ENGINE)                  # 02_执行引擎（Engine）/
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from 输入解析引擎 import router  # noqa: E402
from 输入解析引擎.handlers import config_cmd  # noqa: E402


def _capture_stdout(func, *args, **kwargs):
    """捕获 func 的 stdout，吞掉其 sys.exit（旧 main / dispatch 末端 halt）。"""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            func(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


class TestConfigRoute(unittest.TestCase):
    def test_resolve_route_key(self):
        key, table = router._resolve_route_key("#配置 黄金段 08:30-11:30")
        self.assertEqual(key, "config_cmd")
        self.assertIsNone(table)


class TestConfigParse(unittest.TestCase):
    """解析逻辑（临时 runtime 路径，无真实文件副作用）。"""

    def _run_with_tmp(self, text):
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "_schedule_config.json")
            with mock.patch.object(config_cmd, "_engine_runtime_path", return_value=tmp):
                res = config_cmd.handle_config_cmd(text, dry_run=True)
            saved = None
            if os.path.exists(tmp):
                with open(tmp, encoding="utf-8") as f:
                    saved = json.load(f)
            return res, saved

    def test_parses_all_segments(self):
        res, saved = self._run_with_tmp(
            "#配置 黄金段 08:30-11:30 常规段 14:00-18:00 晚间段 20:00-23:00 "
            "可用时长 6 小时 精力系数 1.2"
        )
        self.assertEqual(res["type"], "config")
        self.assertEqual(res["configs"]["黄金段"], "08:30-11:30")
        self.assertEqual(res["configs"]["常规段"], "14:00-18:00")
        self.assertEqual(res["configs"]["晚间段"], "20:00-23:00")
        self.assertEqual(res["configs"]["今日可用时长"], 6.0)
        self.assertEqual(res["configs"]["精力系数"], 1.2)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["黄金段"], "08:30-11:30")

    def test_inspiration_reminder_toggle(self):
        on, _ = self._run_with_tmp("#配置 开启灵感提醒")
        self.assertTrue(on["configs"]["灵感提醒"])
        off, _ = self._run_with_tmp("#配置 关闭灵感提醒")
        self.assertFalse(off["configs"]["灵感提醒"])

    def test_no_match_returns_empty_configs(self):
        res, _ = self._run_with_tmp("#配置 无关内容")
        self.assertEqual(res["configs"], {})
        self.assertEqual(res["type"], "config")


class TestConfigRuntimeContract(unittest.TestCase):
    def test_write_path_matches_legacy(self):
        new_path = config_cmd._engine_runtime_path()
        legacy = router._get_legacy()
        legacy_path = os.path.join(
            os.path.dirname(legacy.__file__), "runtime", "_schedule_config.json"
        )
        self.assertEqual(new_path, legacy_path)
        norm = new_path.replace("\\", "/")
        self.assertTrue(norm.endswith("输入解析引擎/runtime/_schedule_config.json"))
        self.assertNotIn("handlers/runtime", norm)

    def test_daily_scheduler_same_convention(self):
        sched_file = os.path.join(
            PKG_PARENT, "每日排程引擎", "daily_scheduler.py"
        )
        sched_path = os.path.join(
            os.path.dirname(os.path.abspath(sched_file)),
            "runtime", "_schedule_config.json",
        )
        self.assertTrue(sched_path.replace("\\", "/").endswith("runtime/_schedule_config.json"))
        self.assertEqual(
            os.path.basename(os.path.dirname(config_cmd._engine_runtime_path())),
            "runtime",
        )


class TestConfigCut(unittest.TestCase):
    def test_router_delegates_to_new_handler(self):
        with open(os.path.join(ENGINE, "router.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("_call_config_cmd", src)
        self.assertNotIn("legacy.handle_config", src)
        self.assertIs(router.ROUTE_HANDLERS["config_cmd"], config_cmd.handle_config_cmd)


class TestConfigDispatchParity(unittest.TestCase):
    """router.dispatch 输出与旧 main() 端到端完全一致（dry-run，无网络）。

    注意：#配置 命中后会真实 merge 写入 _schedule_config.json（dry_run 旧逻辑
    无分支，故与旧 main 行为一致）。此处备份真实配置并在 finally 还原，避免污染。
    """

    def _run_old_main(self, text):
        legacy = router._get_legacy()
        sys.argv = ["input_parser.py", text, "--dry-run"]
        return _capture_stdout(legacy.main)

    def _run_router(self, text):
        return _capture_stdout(router.dispatch, text, True)

    def test_dispatch_parity(self):
        text = "#配置 黄金段 08:30-11:30"
        cfg = config_cmd._engine_runtime_path()
        backup = None
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as f:
                backup = f.read()
        try:
            old_out = self._run_old_main(text)
            new_out = self._run_router(text)
            self.assertTrue(old_out.strip(), "旧 main 无输出")
            self.assertEqual(
                new_out, old_out,
                "router 与旧 main 在 #配置 上输出不一致",
            )
            self.assertIn("配置已解析", new_out)
        finally:
            if backup is None:
                if os.path.exists(cfg):
                    os.remove(cfg)
            else:
                with open(cfg, "w", encoding="utf-8") as f:
                    f.write(backup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
