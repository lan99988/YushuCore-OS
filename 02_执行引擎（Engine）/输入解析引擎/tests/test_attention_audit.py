"""
tests/test_attention_audit.py

验证 handlers/attention_audit.py 与旧 handle_attention_audit(1678-1724) 的 1:1 行为一致性。

原则：
- attention_audit 是纯本地文本生成，零网络 / 零文件 / 零外部依赖。
- 因此 parity 可直接端到端新旧 dict 相等对比，无需 mock / tmp_path / 网络隔离。
"""

import os
import sys
import unittest

# 将 02_执行引擎 注入 sys.path，使 `输入解析引擎` 可作为顶层包导入
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(os.path.dirname(HERE))
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import router
from 输入解析引擎.handlers import attention_audit


class TestRoute(unittest.TestCase):
    def test_route_key(self):
        # _resolve_route_key 返回 (route_key, table_name) 元组
        self.assertEqual(router._resolve_route_key("#注意力审计 x")[0], "attention_audit")
        self.assertEqual(router._resolve_route_key("#注意力审计")[0], "attention_audit")


class TestParityVsLegacy(unittest.TestCase):
    def test_parity_with_goals(self):
        legacy = router._get_legacy()
        new_res = attention_audit.handle_attention_audit(
            "#注意力审计 目标1 考研 目标2 公众号", dry_run=False)
        old_res = legacy.handle_attention_audit(
            "#注意力审计 目标1 考研 目标2 公众号", dry_run=False)
        self.assertEqual(new_res, old_res)
        self.assertEqual(new_res["type"], "attention_audit")
        self.assertIn("目标1", new_res["message"])
        self.assertIn("目标2", new_res["message"])

    def test_parity_empty_input(self):
        legacy = router._get_legacy()
        new_res = attention_audit.handle_attention_audit("#注意力审计", dry_run=False)
        old_res = legacy.handle_attention_audit("#注意力审计", dry_run=False)
        self.assertEqual(new_res, old_res)
        # 无目标分支：提示列出目标
        self.assertIn("请列出你最重要的2-4个目标", new_res["message"])

    def test_dry_run_ignored_same_output(self):
        legacy = router._get_legacy()
        new_res = attention_audit.handle_attention_audit(
            "#注意力审计 目标1 考研", dry_run=True)
        old_res = legacy.handle_attention_audit(
            "#注意力审计 目标1 考研", dry_run=True)
        self.assertEqual(new_res, old_res)
        # dry_run 不参与逻辑，输出与普通调用一致
        self.assertNotIn("dry_run", new_res)


class TestCutSignal(unittest.TestCase):
    def test_no_legacy_bridge_reference(self):
        with open(router.__file__, encoding="utf-8") as f:
            router_src = f.read()
        self.assertNotIn("_call_attention_audit", router_src)

    def test_route_points_to_new_handler(self):
        self.assertIs(
            router.ROUTE_HANDLERS["attention_audit"],
            attention_audit.handle_attention_audit,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
