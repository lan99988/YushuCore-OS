"""C-8b deep_record 迁移测试。

验证 handlers/deep_record.py 与旧 handle_deep_record(1419-1523) 的 1:1 行为一致性。
覆盖：路由键 / true cut 信号 / dry_run 不联网 / 飞书写入链 / 失败 error / 异常 fallback / parity。
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
from 输入解析引擎.handlers import deep_record

import datetime as _real_dt


class _FakeNow:
    def strftime(self, fmt):
        return "2026-07-26"


class _FakeDateTime:
    @staticmethod
    def now():
        return _FakeNow()

    @staticmethod
    def strptime(s, f):
        return _real_dt.datetime.strptime(s, f)


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_cli(returncode=0, stderr="", exc=None):
    def _impl(args, json_input=None):
        if exc is not None:
            raise exc
        return _FakeResult(returncode=returncode, stdout='{"data":{}}', stderr=stderr)
    return _impl


class TestDeepRecordRoute(unittest.TestCase):
    def test_route_key(self):
        self.assertEqual(
            router._resolve_route_key("#深度记录 深度3.5小时 心流高 干扰1次")[0],
            "deep_record",
        )


class TestDeepRecordCut(unittest.TestCase):
    def test_bridge_removed(self):
        self.assertFalse(
            hasattr(router, "_call_deep_record"),
            "legacy _call_deep_record bridge still present in router",
        )

    def test_map_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["deep_record"],
            deep_record.handle_deep_record,
        )


class TestDeepRecordBehavior(unittest.TestCase):
    def test_dry_run_no_network(self):
        spy = mock.MagicMock(return_value=_FakeResult(0))
        with mock.patch.object(deep_record, "_run_lark_cli", spy):
            res = deep_record.handle_deep_record(
                "#深度记录 深度3.5小时 心流高 干扰1次", dry_run=True
            )
        self.assertEqual(res["dry_run"], True)
        self.assertEqual(res["type"], "deep_record")
        spy.assert_not_called()

    def test_success_writes_feishu(self):
        spy = mock.MagicMock(return_value=_FakeResult(0))
        with mock.patch.object(deep_record, "_run_lark_cli", spy):
            res = deep_record.handle_deep_record(
                "#深度记录 深度3.5小时 心流高 干扰1次"
            )
        self.assertTrue(res["ok"])
        self.assertIn("record", res)
        spy.assert_called_once()
        args = spy.call_args[0][0]
        self.assertEqual(args[0], "base")
        self.assertIn("+record-upsert", args)
        self.assertIn("--table-id", args)
        self.assertIn(deep_record.DEEP_WORK_TABLE_ID, args)
        self.assertIn("--as", args)

    def test_failure_returns_error(self):
        spy = mock.MagicMock(return_value=_FakeResult(1, stderr="boom"))
        with mock.patch.object(deep_record, "_run_lark_cli", spy):
            res = deep_record.handle_deep_record("#深度记录 深度3.5小时")
        self.assertFalse(res["ok"])
        self.assertIn("error", res)
        self.assertIn("boom", res["error"])

    def test_fallback_on_exception(self):
        spy = mock.MagicMock(side_effect=RuntimeError("net down"))
        with mock.patch.object(deep_record, "_run_lark_cli", spy):
            res = deep_record.handle_deep_record("#深度记录 深度3.5小时")
        self.assertTrue(res["ok"])
        self.assertIn("fallback", res)
        self.assertIn("net down", res["fallback"])


class TestDeepRecordParity(unittest.TestCase):
    def _run_pair(self, text, cli_factory, dry_run=False):
        legacy = router._get_legacy()
        with mock.patch.object(deep_record, "datetime", _FakeDateTime), \
             mock.patch.object(deep_record, "_run_lark_cli", cli_factory), \
             mock.patch.object(legacy, "datetime", _FakeDateTime), \
             mock.patch.object(legacy, "_run_lark_cli", cli_factory):
            old = legacy.handle_deep_record(text, dry_run=dry_run)
            new = deep_record.handle_deep_record(text, dry_run=dry_run)
        return old, new

    def test_parity_dry_run(self):
        old, new = self._run_pair(
            "#深度记录 深度3.5小时 心流高 干扰1次", _make_cli(0), dry_run=True
        )
        self.assertEqual(old, new)

    def test_parity_success(self):
        old, new = self._run_pair(
            "#深度记录 深度3.5小时 心流高 干扰1次", _make_cli(0)
        )
        self.assertEqual(old, new)

    def test_parity_failure(self):
        old, new = self._run_pair(
            "#深度记录 深度3.5小时", _make_cli(1, stderr="e")
        )
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main(verbosity=2)
