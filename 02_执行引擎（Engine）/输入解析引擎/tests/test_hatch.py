"""
tests/test_hatch.py

验证 handlers/hatch.py 与旧 handle_hatch(1000-1091) 的 1:1 行为一致性。

原则：
- 全部用例 monkeypatch 注入假数据，不触碰真实 Feishu / Lark 网络。
- hatch 的 _run_lark_cli 在 dry_run 判断前即调用（查灵感库），故 parity 必须 mock。
- 旧 monolith 自带 _run_lark_cli / insert_to_feishu，parity 时分别 patch
  hatch.* 与 legacy.* 两个模块副本，做到端到端新旧对比且零网络。
"""

import os
import sys
import json
import unittest
import unittest.mock as mock

# 将 02_执行引擎 注入 sys.path，使 `输入解析引擎` 可作为顶层包导入
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import hatch


IDEA_STDOUT = json.dumps({
    "data": {
        "fields": ["标题", "所属项目", "优先级预判", "转化状态", "record_id"],
        "data": [
            ["读论文", "数学二", "P1-重要不紧急", "待孵化", "rec123"],
        ],
    }
})


class _FakeResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def _fake_cli_factory(query_stdout):
    """根据 args 区分查询/更新，返回对应假结果。"""
    def _fake_cli(args_list, json_input=None):
        if len(args_list) >= 2 and args_list[1] == "+record-list":
            return _FakeResult(0, query_stdout)
        # +record-update 等写操作
        return _FakeResult(0, "{}")
    return _fake_cli


class TestRoute(unittest.TestCase):
    def test_route_key(self):
        # _resolve_route_key 返回 (route_key, table_name) 元组
        self.assertEqual(router._resolve_route_key("#孵化 数学二")[0], "hatch")
        self.assertEqual(router._resolve_route_key("#孵化")[0], "hatch")


class TestReturns(unittest.TestCase):
    def test_success_writes_task_and_updates_idea(self):
        fake = _fake_cli_factory(IDEA_STDOUT)
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake) as m_cli, \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = hatch.handle_hatch("#孵化", dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "hatch")
        self.assertEqual(res["message"], "已孵化灵感 → 创建任务：'读论文'")
        self.assertEqual(res["details"]["标题"], "[灵感孵化] 读论文")
        self.assertEqual(res["details"]["状态"], "待收集")
        self.assertEqual(res["details"]["预估耗时"], 60)
        # 写入执行库
        m_ins.assert_called_once_with("执行库", res["details"])
        # 更新灵感库转化状态（record-update 调用）
        update_calls = [c for c in m_cli.call_args_list
                        if len(c.args) >= 1 and c.args[0][1] == "+record-update"]
        self.assertEqual(len(update_calls), 1)
        self.assertIn('{"转化状态": "已孵化"}', update_calls[0].args[0])

    def test_dry_run_returns_payload_and_skips_write(self):
        fake = _fake_cli_factory(IDEA_STDOUT)
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = hatch.handle_hatch("#孵化 数学二", dry_run=True)

        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["table"], "执行库")
        self.assertEqual(res["payload"]["标题"], "[灵感孵化] 读论文")
        self.assertIn("source", res)
        # dry_run 分支在写入前返回，insert_to_feishu 不应被调用
        m_ins.assert_not_called()

    def test_no_candidates(self):
        empty = json.dumps({"data": {"fields": ["标题", "转化状态"], "data": [
            ["已做", "数学二", "已孵化"],
        ]}})
        fake = _fake_cli_factory(empty)
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = hatch.handle_hatch("#孵化", dry_run=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["message"], "灵感库中没有待孵化的灵感")
        m_ins.assert_not_called()

    def test_network_failure(self):
        fake = _fake_cli_factory("")  # 不会被用到（returncode != 0 提前返回）
        def _always_fail(args_list, json_input=None):
            return _FakeResult(1, "")
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=_always_fail), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = hatch.handle_hatch("#孵化", dry_run=False)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "读取灵感库失败")
        m_ins.assert_not_called()

    def test_parse_failure(self):
        fake = _fake_cli_factory("这不是合法JSON")
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = hatch.handle_hatch("#孵化", dry_run=False)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "解析灵感库数据失败")
        m_ins.assert_not_called()


class TestParityVsLegacy(unittest.TestCase):
    def test_parity_success(self):
        legacy = router._get_legacy()
        fake = _fake_cli_factory(IDEA_STDOUT)
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(legacy, "insert_to_feishu", return_value={"ok": True}):
            new_res = hatch.handle_hatch("#孵化", dry_run=False)
            old_res = legacy.handle_hatch("#孵化", dry_run=False)
        self.assertEqual(new_res, old_res)

    def test_parity_dry_run(self):
        legacy = router._get_legacy()
        fake = _fake_cli_factory(IDEA_STDOUT)
        with mock.patch.object(hatch, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(hatch, "insert_to_feishu", return_value={"ok": True}), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(legacy, "insert_to_feishu", return_value={"ok": True}):
            new_res = hatch.handle_hatch("#孵化", dry_run=True)
            old_res = legacy.handle_hatch("#孵化", dry_run=True)
        self.assertEqual(new_res, old_res)


class TestCutSignal(unittest.TestCase):
    def test_no_legacy_bridge_reference(self):
        with open(router.__file__, encoding="utf-8") as f:
            router_src = f.read()
        self.assertNotIn("_call_hatch", router_src)

    def test_route_points_to_new_handler(self):
        self.assertIs(router.ROUTE_HANDLERS["hatch"], hatch.handle_hatch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
