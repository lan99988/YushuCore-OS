"""
builders.py 迁移正确性测试

原则：比对旧（input_parser_old）与新（输入解析引擎.builders）输出逐字一致。
build_record 的 财务/社交 分支含 datetime.now() 日期字段，测试中以冻结 datetime
mock 注入 old / new 两端，确保日期值确定且两端一致。
format_output 覆盖多 type 分支。
"""

import importlib.util
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
from 输入解析引擎 import builders as new
from 输入解析引擎 import parser as new_parser


class _FrozenDateTime:
    """冻结 datetime：now() 固定返回 2026/07/24，避免日期字段非确定性"""
    @classmethod
    def now(cls):
        return cls()

    def strftime(self, fmt):
        return "2026/07/24"


def make_inputs(text):
    """用新 parser 派生 (table, title, vars, raw_text)，作为两端共同输入"""
    table, _ = new_parser.detect_prefix(text)
    vars_ = new_parser.extract_variables(text)
    title = new_parser.extract_main_content(text)
    return table, title, vars_, text


class TestBuildRecordParity(unittest.TestCase):

    # 三个确定性分支（用户指定）
    def test_task(self):
        args = make_inputs("#任务 写公众号文章")
        self.assertEqual(old.build_record(*args), new.build_record(*args))

    def test_idea(self):
        args = make_inputs("#灵感 AI Agent系统")
        self.assertEqual(old.build_record(*args), new.build_record(*args))

    def test_bug(self):
        args = make_inputs("#Bug 飞书同步失败")
        self.assertEqual(old.build_record(*args), new.build_record(*args))

    # 日期分支：冻结 datetime 后比对（覆盖 财务流水表 / 社交关系表）
    def test_bill_with_frozen_date(self):
        args = make_inputs("#账单 午饭 35元")
        with patch.object(old, "datetime", _FrozenDateTime), \
             patch.object(new, "datetime", _FrozenDateTime):
            old_rec = old.build_record(*args)
            new_rec = new.build_record(*args)
        self.assertEqual(old_rec, new_rec)
        self.assertEqual(old_rec.get("日期"), "2026/07/24")

    def test_social_with_frozen_date(self):
        args = make_inputs("#社交 张三 微信好友 吃饭")
        with patch.object(old, "datetime", _FrozenDateTime), \
             patch.object(new, "datetime", _FrozenDateTime):
            old_rec = old.build_record(*args)
            new_rec = new.build_record(*args)
        self.assertEqual(old_rec, new_rec)
        self.assertEqual(old_rec.get("日期"), "2026/07/24")
        self.assertEqual(old_rec.get("联系人"), "张三")


class TestFormatOutputParity(unittest.TestCase):

    CASES = [
        {"ok": False, "error": "未知错误"},
        {"ok": True, "type": "energy_status", "message": "状态正常", "suggestion": "保持"},
        {"ok": True, "type": "hatch", "dry_run": True, "table": "灵感库",
         "source": {"标题": "灵感A"}, "payload": {"标题": "x"}},
        {"ok": True, "type": "review", "message": "本周复盘"},
        {"ok": True, "type": "config", "configs": {"a": 1, "b": "y"}},
        {"ok": True, "type": "calendar", "message": "已同步"},
        {"ok": True, "type": "deep_plan", "message": "深度4h"},
        {"ok": True, "type": "deep_review", "message": "深度复盘"},
        {"ok": True, "type": "attention_audit", "message": "注意力审计"},
        {"ok": True, "type": "lightweight", "dry_run": True, "message": "临时任务"},
        {"ok": True, "type": "lightweight", "error": "失败"},
        {"ok": True, "type": "sync_taskbox", "message": "同步"},
        {"ok": True, "type": "habit_create", "message": "习惯已建"},
        {"ok": True, "type": "habit_error", "message": "习惯错误"},
        {"ok": True, "type": "competition", "message": "比赛详情"},
        {"ok": True, "deduplicated": True, "title": "重复任务"},
        {"ok": True, "dry_run": True, "table": "执行库", "payload": {"标题": "z"}},
        {"ok": True, "table": "执行库"},
    ]

    def test_format_output_parity(self):
        for r in self.CASES:
            with self.subTest(result=r):
                self.assertEqual(
                    old.format_output(r),
                    new.format_output(r),
                    msg=f"format_output 不一致: {r!r}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
