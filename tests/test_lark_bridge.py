"""
test_lark_bridge.py — 基础设施层迁移验证（Step2-2）

仅做单元验证，不触碰真实飞书。

测试覆盖：
1. 命令构造：拼接出的 bash 命令须包含 lark-cli / base token / --as=user
2. 回退逻辑：所有 bash 路径不可用 → 真实行为是抛出 FileNotFoundError
   （注：input_parser 的 _run_lark_cli 无 node run.js 分支，node 回退在健康检查工具里；
    此处按真实行为断言，不伪造不存在的分支）
3. 错误返回：模拟超时 → insert_to_feishu 返回 {"ok": False, "error": ...}
"""

import os
import sys
import unittest
from unittest import mock

# ---- 让测试能 import 中文包名的「输入解析引擎」----
# 包所在父目录为 02_执行引擎（Engine），其路径可含任意字符；
# 只需把它加入 sys.path，再 import 合法标识符包名 输入解析引擎 即可。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PARENT = os.path.join(ROOT, "02_执行引擎（Engine）")
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎 import config, lark_bridge, feishu_write, validators  # noqa: E402


class TestCommandConstruction(unittest.TestCase):
    """验证命令拼接：lark-cli + base token + --as=user 均存在"""

    def test_command_contains_cli_token_as_user(self):
        captured = {}

        def fake_run(cmd_args, **kwargs):
            # bash -c 的脚本字符串是 cmd_args[-1]
            captured["cmd"] = cmd_args[-1]

            class _R:
                stdout = b'{"code":0,"data":{"code":0}}'
                stderr = b""
                returncode = 0

            return _R()

        with mock.patch.object(lark_bridge.subprocess, "run", fake_run):
            lark_bridge._run_lark_cli([
                "base", "+record-list",
                "--base-token", config.BASE_TOKEN,
                "--table-id", config.TABLES["执行库"],
                "--as", "user", "--format", "json",
            ])

        cmd = captured["cmd"]
        self.assertIn("lark-cli", cmd)          # 客户端路径
        self.assertIn(config.BASE_TOKEN, cmd)   # base token
        self.assertIn("--as", cmd)              # 身份参数
        self.assertIn("user", cmd)              # 用户身份


class TestLarkCliUnavailable(unittest.TestCase):
    """模拟 lark-cli 不可用：真实回退行为是抛出 FileNotFoundError"""

    def test_raises_when_all_bash_missing(self):
        # _run_lark_cli 无 node run.js 分支；全部 bash 失败则抛 FileNotFoundError
        with mock.patch.object(lark_bridge.subprocess, "run", side_effect=FileNotFoundError("no bash")):
            with self.assertRaises(FileNotFoundError):
                lark_bridge._run_lark_cli(["base", "+record-list"])


class TestErrorReturnStructure(unittest.TestCase):
    """模拟超时：insert_to_feishu 应返回 {ok: False, error: ...}"""

    def test_timeout_returns_error_dict(self):
        # 超时(TimeoutError, 属 OSError)会被 _run_lark_cli 的 except OSError 捕获，
        # 走完所有 bash 路径后抛 FileNotFoundError，最终由 insert_to_feishu 的
        # except Exception 兜住，返回 {ok: False, error: ...}
        # 注：mock os.remove 仅为避开测试沙箱 safe-delete 钩子对清理阶段 os.remove 的拦截，
        # 不影响被测逻辑。
        with mock.patch.object(lark_bridge.subprocess, "run", side_effect=TimeoutError("timeout")), \
             mock.patch.object(lark_bridge.os, "remove", lambda *a, **k: None):
            res = feishu_write.insert_to_feishu("执行库", {"标题": "测试"}, dry_run=False)

        self.assertFalse(res.get("ok"))
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
