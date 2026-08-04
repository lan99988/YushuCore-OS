"""
validators.py 迁移正确性测试

说明：
- 旧文件 input_parser_old.py 中仅有 `deduplicate_check()`（808-857 行）。
- `_validate_record` 在旧文件中**并不存在**（已全文检索 validate/校验/_validate_record
  均无命中）。属于计划中假设的、实际未实现的函数。按「搬家不装修」原则，
  **不凭空新增** `_validate_record`，仅对真实存在的 `deduplicate_check` 做 parity。
- deduplicate_check 依赖网络（_run_lark_cli），测试中以相同 mock 注入 old / new 两端。
"""

import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import patch

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(WORKSPACE, "02_执行引擎（Engine）", "输入解析引擎")

# 1. 加载旧模块（单体文件）
old_path = os.path.join(ENGINE_DIR, "input_parser_old.py")
spec = importlib.util.spec_from_file_location("input_parser_old", old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

# 2. 加载新模块（包内）
sys.path.insert(0, os.path.join(WORKSPACE, "02_执行引擎（Engine）"))
from 输入解析引擎 import validators as new


class _FakeResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


# 执行库返回：含一条「写公众号文章 / 2026/07/24」的已存在记录
_FAKE_JSON = json.dumps({
    "data": {
        "fields": ["标题", "截止日期"],
        "data": [
            ["写公众号文章", "2026/07/24"],
        ],
    }
})


class TestDeduplicateCheckParity(unittest.TestCase):

    # ---- 纯分支（不依赖网络，无需 mock）----
    def test_non_exec_table_returns_false(self):
        self.assertEqual(
            old.deduplicate_check("灵感库", "写公众号文章", "2026/07/24"),
            new.deduplicate_check("灵感库", "写公众号文章", "2026/07/24"),
        )
        self.assertFalse(new.deduplicate_check("灵感库", "x", "2026/07/24"))

    def test_dry_run_returns_false(self):
        self.assertEqual(
            old.deduplicate_check("执行库", "写公众号文章", "2026/07/24", dry_run=True),
            new.deduplicate_check("执行库", "写公众号文章", "2026/07/24", dry_run=True),
        )
        self.assertFalse(new.deduplicate_check("执行库", "x", "2026/07/24", dry_run=True))

    def test_empty_target_date_returns_false(self):
        self.assertEqual(
            old.deduplicate_check("执行库", "写公众号文章", ""),
            new.deduplicate_check("执行库", "写公众号文章", ""),
        )
        self.assertFalse(new.deduplicate_check("执行库", "x", ""))

    # ---- 网络分支（两端注入相同 mock）----
    def test_duplicate_detected_parity(self):
        fake = _FakeResult(0, _FAKE_JSON)
        with patch.object(old, "_run_lark_cli", return_value=fake), \
             patch.object(new, "_run_lark_cli", return_value=fake):
            old_res = old.deduplicate_check("执行库", "写公众号文章", "2026/07/24")
            new_res = new.deduplicate_check("执行库", "写公众号文章", "2026/07/24")
        self.assertEqual(old_res, new_res)
        self.assertTrue(old_res, "应检测到重复（标题+日期匹配）")

    def test_no_duplicate_parity(self):
        fake = _FakeResult(0, _FAKE_JSON)
        with patch.object(old, "_run_lark_cli", return_value=fake), \
             patch.object(new, "_run_lark_cli", return_value=fake):
            old_res = old.deduplicate_check("执行库", "学习AI Agent", "2026/07/24")
            new_res = new.deduplicate_check("执行库", "学习AI Agent", "2026/07/24")
        self.assertEqual(old_res, new_res)
        self.assertFalse(old_res, "标题不匹配应返回 False")

    def test_cli_failure_returns_false_parity(self):
        # 网络/CLI 异常（returncode != 0）应返回 False，不抛异常
        fake = _FakeResult(1, "error")
        with patch.object(old, "_run_lark_cli", return_value=fake), \
             patch.object(new, "_run_lark_cli", return_value=fake):
            old_res = old.deduplicate_check("执行库", "写公众号文章", "2026/07/24")
            new_res = new.deduplicate_check("执行库", "写公众号文章", "2026/07/24")
        self.assertEqual(old_res, new_res)
        self.assertFalse(old_res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
