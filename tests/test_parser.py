"""
parser.py 迁移正确性测试

原则：纯函数层比对
- 旧实现：input_parser_old.py（单体文件，作为独立模块导入）
- 新实现：输入解析引擎.parser（包内模块）

比对粒度：同输入 → 同输出（逐字一致）
不依赖飞书 / 网络 / 外部状态。
"""

import importlib.util
import os
import sys
import unittest

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(WORKSPACE, "02_执行引擎（Engine）", "输入解析引擎")

# 1. 加载旧模块（单体文件）
old_path = os.path.join(ENGINE_DIR, "input_parser_old.py")
spec = importlib.util.spec_from_file_location("input_parser_old", old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

# 2. 加载新模块（包内）
sys.path.insert(0, os.path.join(WORKSPACE, "02_执行引擎（Engine）"))
from 输入解析引擎 import parser as new


class TestParserParity(unittest.TestCase):

    CASES = [
        "#任务 写公众号文章",
        "#任务 写文章 [项目：公众号]",
        "#账单 午饭 30",
        "#知识 学习Transformer",
        "#灵感 一个产品想法 转化率优化",
        "#Bug 登录接口偶发崩溃 [严重程度：崩溃]",
        "#任务 完成论文第二章 #高 #硬骨头 #冲刺",
        "#任务 写周报 [责任人：workbuddy] [精力：高]",
        "#比赛 数学建模 初赛 2026/09/12",
        "无前缀的随手笔记 买牛奶",
    ]

    def test_detect_prefix_parity(self):
        for text in self.CASES:
            self.assertEqual(
                old.detect_prefix(text),
                new.detect_prefix(text),
                msg=f"detect_prefix 不一致: {text!r}",
            )

    def test_extract_variables_parity(self):
        for text in self.CASES:
            self.assertEqual(
                old.extract_variables(text),
                new.extract_variables(text),
                msg=f"extract_variables 不一致: {text!r}",
            )

    def test_extract_main_content_parity(self):
        for text in self.CASES:
            self.assertEqual(
                old.extract_main_content(text),
                new.extract_main_content(text),
                msg=f"extract_main_content 不一致: {text!r}",
            )

    def test_parse_date_parity(self):
        date_samples = [
            "2026/07/05",
            "2026-12-20",
            "7月5日",
            "15日",
            "不是日期",
            "",
        ]
        for ds in date_samples:
            self.assertEqual(
                old.parse_date(ds),
                new.parse_date(ds),
                msg=f"parse_date 不一致: {ds!r}",
            )

    def test_auto_detect_category_parity(self):
        for proj in ["考研", "公众号", "数学二", None, "随便"]:
            self.assertEqual(
                old.auto_detect_category(proj),
                new.auto_detect_category(proj),
                msg=f"auto_detect_category 不一致: {proj!r}",
            )

    def test_parse_date_deterministic_for_cases(self):
        # 用例中不含相对日期，确保 extract_variables 不触发非确定性
        for text in self.CASES:
            self.assertNotIn("截止日期", new.extract_variables(text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
