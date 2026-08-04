"""
extractor.py 迁移正确性测试

原则：纯函数层比对
- 旧实现：input_parser_old.py（单体文件，作为独立模块导入）
- 新实现：输入解析引擎.extractor（包内模块）

比对粒度：同输入 → 同输出（逐字一致）。
build_subject_completion_update 依赖网络（_run_lark_cli），测试中以相同 mock
注入 old / new 两端，仅比对「网络返回 → 处理后结果」的纯逻辑一致性。
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
from 输入解析引擎 import extractor as new


class _FakeResult:
    """模拟 subprocess.CompletedProcess，仅提供 returncode / stdout"""

    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


# build_subject_completion_update 的固定 mock 返回（知识笔记表/科目进度基线结构）
_FAKE_JSON = json.dumps({
    "data": {
        "fields": ["科目", "完成率"],
        "data": [
            ["数学", 10.0],
            ["英语", 5.0],
            ["政治", 3.0],
        ],
    }
})


class TestExtractorParity(unittest.TestCase):

    def test_parse_bill_vars_parity(self):
        cases = [
            "#账单 午饭 35元",
            "#账单 打车 28块",
            "#财务 工资 8000收入",
            "#账单 买书 56",
            "无前缀 奶茶 18元",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    old.parse_bill_vars(text),
                    new.parse_bill_vars(text),
                    msg=f"parse_bill_vars 不一致: {text!r}",
                )

    def test_parse_social_vars_parity(self):
        cases = [
            "#社交 张三 微信好友",
            "#关系 李四 同学 生日:2000-01-01",
            "#人脉 王五 同事 打电话",
            "#社交 赵六 家人 吃饭",
            "#社交 孙七 合作伙伴 合作",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    old.parse_social_vars(text),
                    new.parse_social_vars(text),
                    msg=f"parse_social_vars 不一致: {text!r}",
                )

    def test_parse_create_vars_parity(self):
        cases = [
            "#创作 AI文章",
            "#作品 写代码 进行中",
            "#创作 视频 已发布 关联灵感:灵感A",
            "#创作 设计 草稿",
            "无前缀 写文档",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    old.parse_create_vars(text),
                    new.parse_create_vars(text),
                    msg=f"parse_create_vars 不一致: {text!r}",
                )

    def test_parse_knowledge_vars_parity(self):
        cases = [
            "#知识 学习Transformer",
            "#笔记 来源:书籍 数学 常青笔记",
            "#学 来源:视频 英语 MOC 关联:记录X",
            "#知识 来源:课程 政治 关联灵感:灵感Y",
            "无前缀 编程经验分享",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    old.parse_knowledge_vars(text),
                    new.parse_knowledge_vars(text),
                    msg=f"parse_knowledge_vars 不一致: {text!r}",
                )

    def test_build_social_title_parity(self):
        # build_social_title 在旧模块中被后定义(711行)覆盖，应为纯函数版本
        cases = [
            "#社交 张三 微信好友",
            "#关系 李四 同学 生日:2000-01-01",
            "#人脉 王五 合作伙伴",
            "无前缀 赵六 家人",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    old.build_social_title(text),
                    new.build_social_title(text),
                    msg=f"build_social_title 不一致: {text!r}",
                )

    def test_build_subject_completion_update_parity(self):
        inferred = {"数学": 20.0, "英语": 15.0}
        fake = _FakeResult(0, _FAKE_JSON)
        # 两端注入相同 mock，仅比对纯处理逻辑
        with patch.object(old, "_run_lark_cli", return_value=fake), \
             patch.object(new, "_run_lark_cli", return_value=fake):
            old_res = old.build_subject_completion_update(inferred)
            new_res = new.build_subject_completion_update(inferred)
        self.assertEqual(old_res, new_res, msg="build_subject_completion_update 不一致")
        # 预期只返回 inferred 中命中科目的项
        self.assertEqual(old_res, {"数学": 20.0, "英语": 15.0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
