"""
飞书CLI桥接层

封装 _run_lark_cli：在 Windows 下通过 Git Bash 调用 lark-cli，
兼容编码回退、超时以及 stdout/stderr 的尝试解码处理。

迁移来源：input_parser.py 行 727-806，逻辑 100% 保留，
仅将全局 LARK_CLI 改为本包内 from .config 导入。
"""

import os
import subprocess
import uuid

from .config import LARK_CLI


def _run_lark_cli(args_list, json_input=None):
    """运行lark-cli命令，兼容Windows环境

    Args:
        args_list: 命令参数列表（不含lark-cli本身）
        json_input: 可选的JSON字符串，写入临时文件后通过 @file 传给 --json
    """
    # 尝试几种编码读取输出
    def try_decode(data):
        if data is None:
            return ""
        for enc in ["utf-8", "gbk", "gb2312", "cp936"]:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")

    # lark-cli @file 只接受当前目录的相对路径，用唯一文件名
    tmp_path = None
    if json_input:
        tmp_name = f"_lark_tmp_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json_input)
        # 替换 --json value 为 --json @tmp_name
        new_args = []
        i = 0
        while i < len(args_list):
            if args_list[i] == "--json" and i + 1 < len(args_list):
                new_args.append("--json")
                new_args.append(f"@{tmp_name}")
                i += 2
            else:
                new_args.append(args_list[i])
                i += 1
        args_list = new_args

    # 构建完整的命令行字符串（bash -c需要单参数）
    cli_path = LARK_CLI.replace("\\", "/")
    cmd_parts = [f'"{cli_path}"'] + [f'"{a}"' for a in args_list]
    cmd_str = " ".join(cmd_parts)

    # 清理临时文件
    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # 通过Git Bash调用
    bash_paths = [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        "bash",
    ]
    last_error = None
    for bash_cmd in bash_paths:
        try:
            result = subprocess.run(
                [bash_cmd, "-c", cmd_str],
                capture_output=True, timeout=30
            )
            stdout = try_decode(result.stdout)
            stderr = try_decode(result.stderr)
            result.stdout = stdout
            result.stderr = stderr
            _cleanup()
            return result
        except (FileNotFoundError, OSError) as e:
            last_error = e
            continue

    _cleanup()
    raise FileNotFoundError(f"lark-cli not found via any method: {last_error}")
