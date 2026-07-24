#!/usr/bin/env python3
"""
深度工作晚间提醒脚本
======================
每晚 21:30 运行，提醒用户记录当天的深度工作表现。

用法：
    python "05_自动化工作流（Automation）/脚本/deep_work_reminder.py"          # 正常模式
    python "05_自动化工作流（Automation）/脚本/deep_work_reminder.py" --dry-run  # 测试模式
"""

import json
import subprocess
import os
import sys
import uuid
from datetime import datetime, date, timedelta

BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
USER_OPEN_ID = "ou_adf2c637b6ddd79c0af429ad5da3a746"
NODE_PATH = r"C:\Users\26326\.workbuddy\binaries\node\versions\22.22.2\node.exe"
CLI_JS = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\@larksuite\cli\scripts\run.js"


def _run_lark(args_list, json_input=None):
    """运行 lark-cli 命令（通过 Node.js 直接调用，避免 shell 转义问题）"""
    tmp_path = None
    if json_input:
        tmp_name = f"_lark_tmp_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json_input)
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

    def try_decode(data):
        if data is None:
            return ""
        for enc in ["utf-8", "gbk", "gb2312", "cp936"]:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")

    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    cmd = [NODE_PATH, CLI_JS] + args_list
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    result.stdout = try_decode(result.stdout)
    result.stderr = try_decode(result.stderr)
    _cleanup()
    return result


def send_message(text, dry_run=False):
    """通过飞书发送消息"""
    if dry_run:
        print(f"[DRY-RUN] 将发送消息:\n{text}")
        return True
    result = _run_lark([
        "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--markdown", text,
        "--as", "user",
    ])
    return result.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    today = date.today().strftime("%Y/%m/%d")
    weekday = date.today().strftime("%A")

    # 检查今天是否有深度工作记录
    try:
        result = _run_lark([
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", "tblmAz37er4CEbL0",
            "--as", "user",
            "--limit", "50",
            "--format", "json",
        ])
        has_record_today = False
        if result.returncode == 0:
            resp = json.loads(result.stdout)
            d = resp.get("data", {})
            field_names = d.get("fields", [])
            data_array = d.get("data", [])
            for row in data_array:
                fields = dict(zip(field_names, row))
                def _get(fn, default=None):
                    v = fields.get(fn, default)
                    if isinstance(v, list):
                        return v[0] if v else default
                    return v
                dr = _get("日期", "")
                if dr and str(dr)[:10].replace("-", "/") == today:
                    has_record_today = True
                    break
    except Exception:
        has_record_today = False

    # 构造消息
    lines = []
    lines.append("🔴 【深度工作晚间提醒】")
    lines.append("")

    if has_record_today:
        lines.append("✅ 你今天已经有深度工作记录了！")
        lines.append("")
        lines.append("来看看完整的数据：")
        lines.append("  · 进入飞书Base → 「深度工作追踪表」查看全貌")
        lines.append("  · 或在WorkBuddy输入：`#复盘深度 1` 查看概况")
    else:
        lines.append("📝 今天还没记录深度工作表现呢！")
        lines.append("")
        lines.append(f"花30秒记录一下：")
        lines.append(f"  `#深度记录 深度X小时 心流X 干扰X次`")
        lines.append("")
        lines.append("示例：")
        lines.append("  · `#深度记录 深度3小时 心流高 干扰0次`")
        lines.append("  · `#深度记录 深度2.5小时 心流中 干扰2次`")
        lines.append("")
        lines.append("💡 坚持记录 = 看到自己的进步！")

    lines.append("")
    lines.append("════════════════════════════════")
    lines.append(f"📆 {today} {weekday}")

    msg = "\n".join(lines)
    print(msg)

    if not dry_run:
        success = send_message(msg)
        if success:
            print("✅ 消息已推送")
        else:
            print("❌ 推送失败")

    return 0


if __name__ == "__main__":
    sys.exit(main())
