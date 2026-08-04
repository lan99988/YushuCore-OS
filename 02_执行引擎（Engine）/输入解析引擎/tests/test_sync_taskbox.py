"""
tests/test_sync_taskbox.py

验证 handlers/sync_taskbox.py 与旧 handle_sync_taskbox(2126-2246) 的 1:1 行为一致性。

原则：
- sync_taskbox 多次调用 _run_lark_cli（任务框读 + 执行库分页读）+ insert_to_feishu（写），
  全部 monkeypatch 注入假数据，不触碰真实 Feishu / Lark 网络。
- due 日期用固定 timestamp 注入，避开 datetime.now() 兜底漂移。
- parity：同时 patch sync_taskbox.* 与 legacy.* 双副本，端到端新旧 dict 相等（零网络）。
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
from 输入解析引擎.handlers import sync_taskbox


# 固定 due timestamp，避开 datetime.now() 漂移
TASK_STDOUT = json.dumps({
    "data": {
        "items": [
            {"summary": "写周报", "status": "in_progress",
             "due": {"timestamp": 1720000000}, "description": "d1"},
            {"summary": "[临时] 倒垃圾", "status": "in_progress", "due": {}},
            {"summary": "完成V1评审", "status": "done", "due": {}},
            {"summary": "已在库任务", "status": "in_progress",
             "due": {"timestamp": 1720000000}},
        ]
    }
})

BASE_PAGE_SINGLE = json.dumps({
    "data": {
        "fields": ["标题"],
        "data": [["已在库任务"]],
        "has_more": False,
    }
})

BASE_PAGE_FIRST = json.dumps({
    "data": {
        "fields": ["标题"],
        "data": [["已在库任务"]],
        "has_more": True,
    }
})

BASE_PAGE_SECOND = json.dumps({
    "data": {
        "fields": ["标题"],
        "data": [["另一个已存在"]],
        "has_more": False,
    }
})

BASE_PAGE_TERMINAL = json.dumps({
    "data": {
        "fields": ["标题"],
        "data": [],
        "has_more": False,
    }
})


class _FakeResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _fake_cli_factory(task_stdout, *base_pages):
    """base_pages: 依次返回的 base record-list 页（分页测试用多个）。
    每次调用工厂得到独立 cli，cli 内 base_iter 在单次 handler 调用内持续翻页。"""
    def _fake(args_list, json_input=None):
        if args_list and args_list[0] == "task":
            return _FakeResult(0, task_stdout)
        # base record-list：cli 内持有一个迭代器，分页时逐页推进
        if not hasattr(_fake, "_base_iter"):
            _fake._base_iter = iter(base_pages)
        try:
            return _FakeResult(0, next(_fake._base_iter))
        except StopIteration:
            return _FakeResult(0, json.dumps({"data": {"fields": ["标题"], "data": [], "has_more": False}}))
    return _fake


class TestRoute(unittest.TestCase):
    def test_route_key(self):
        self.assertEqual(router._resolve_route_key("#同步任务框 x")[0], "sync_taskbox")
        self.assertEqual(router._resolve_route_key("#同步任务框")[0], "sync_taskbox")


class TestClassification(unittest.TestCase):
    def test_classification_and_success_write(self):
        fake = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_SINGLE)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake) as m_cli, \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["type"], "sync_taskbox")
        # 分类计数：temp/done/already 各 1，to_sync=写周报
        # 注：报告仅列出 temp_skip 与 to_sync 的明细，done/already 只显示计数
        self.assertIn("轻量任务（带[临时]，跳过不入库）：1 个", res["message"])
        self.assertIn("[临时] 倒垃圾", res["message"])
        self.assertIn("已完成任务（跳过）：1 个", res["message"])
        self.assertIn("已同步正式任务（跳过）：1 个", res["message"])
        self.assertIn("待入库正式任务：1 个", res["message"])
        self.assertIn("已同步 1 个正式任务", res["message"])
        self.assertEqual(res["created"], ["写周报"])
        # insert_to_feishu 带 target_date 与 dry_run=False
        m_ins.assert_called_once()
        call_kwargs = m_ins.call_args
        self.assertEqual(call_kwargs.args[0], "执行库")
        self.assertEqual(call_kwargs.kwargs.get("target_date"), "1970/01/21")
        self.assertFalse(call_kwargs.kwargs.get("dry_run"))

    def test_dry_run_no_write(self):
        fake = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_SINGLE)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框 --dry-run", dry_run=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["type"], "sync_taskbox")
        self.assertEqual(len(res["to_sync"]), 1)
        self.assertEqual(res["to_sync"][0]["summary"], "写周报")
        # dry_run 分支在写入前返回，insert_to_feishu 不应被调用
        m_ins.assert_not_called()

    def test_empty_items(self):
        empty = json.dumps({"data": {"items": []}})
        fake = _fake_cli_factory(empty, BASE_PAGE_SINGLE)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["created"], [])
        self.assertIn("待入库正式任务：0 个", res["message"])
        m_ins.assert_not_called()

    def test_read_failure(self):
        def _fail(args_list, json_input=None):
            return _FakeResult(1, "")
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=_fail), \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=False)
        self.assertFalse(res["ok"])
        self.assertEqual(res["type"], "sync_taskbox")
        self.assertIn("读取任务框失败", res["error"])
        m_ins.assert_not_called()

    def test_deduplicated_not_counted(self):
        # to_sync 非空，但 insert 返回去重 → created 为空
        fake = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_SINGLE)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake), \
             mock.patch.object(sync_taskbox, "insert_to_feishu",
                               return_value={"ok": True, "deduplicated": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["created"], [])
        self.assertIn("已同步 0 个正式任务", res["message"])

    def test_pagination(self):
        # 两页 base 数据，has_more 串联：第一页 has_more=True，第二页 has_more=False 终止
        fake = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_FIRST, BASE_PAGE_SECOND, BASE_PAGE_TERMINAL)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake) as m_cli, \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}) as m_ins:
            res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=False)
        # base record-list 被调用两次（分页推进：page0→page1，page1 has_more=False 终止）
        base_calls = [c for c in m_cli.call_args_list
                      if c.args and c.args[0][0] == "base"]
        self.assertEqual(len(base_calls), 2)
        # 报告仅列 temp/to_sync 明细，already 只显示计数；分页正确性由 base_calls==2 验证
        self.assertIn("已同步正式任务（跳过）：1 个", res["message"])


class TestParityVsLegacy(unittest.TestCase):
    def _run(self, dry_run):
        legacy = router._get_legacy()
        # 新旧 handler 各自独立 cli 工厂，避免 base_iter 跨调用污染
        fake_new = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_SINGLE)
        fake_old = _fake_cli_factory(TASK_STDOUT, BASE_PAGE_SINGLE)
        with mock.patch.object(sync_taskbox, "_run_lark_cli", side_effect=fake_new), \
             mock.patch.object(sync_taskbox, "insert_to_feishu", return_value={"ok": True}), \
             mock.patch.object(legacy, "_run_lark_cli", side_effect=fake_old), \
             mock.patch.object(legacy, "insert_to_feishu", return_value={"ok": True}):
            new_res = sync_taskbox.handle_sync_taskbox("#同步任务框", dry_run=dry_run)
            old_res = legacy.handle_sync_taskbox("#同步任务框", dry_run=dry_run)
        return new_res, old_res

    def test_parity_success(self):
        new_res, old_res = self._run(False)
        self.assertEqual(new_res, old_res)

    def test_parity_dry_run(self):
        new_res, old_res = self._run(True)
        self.assertEqual(new_res, old_res)


class TestCutSignal(unittest.TestCase):
    def test_no_legacy_bridge_reference(self):
        with open(router.__file__, encoding="utf-8") as f:
            router_src = f.read()
        self.assertNotIn("_call_sync_taskbox", router_src)

    def test_route_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["sync_taskbox"],
            sync_taskbox.handle_sync_taskbox,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
