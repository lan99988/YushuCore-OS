"""
轻量任务 handler（Step2-4-C-1）

从 input_parser_old.handle_lightweight_task 原样迁移，业务行为不变（搬家不装修）。
处理 #临时 指令：创建轻量任务，仅入飞书任务框，不写执行库。

依赖已全部迁移到本包：
- extract_variables / extract_main_content  -> ..parser
- _run_lark_cli                           -> ..lark_bridge
"""

import json
import os
import uuid
from datetime import datetime

from ..parser import extract_variables, extract_main_content
from ..lark_bridge import _run_lark_cli


def handle_lightweight_task(raw_text, dry_run=False):
    """处理 #临时 指令：创建轻量任务，仅入飞书任务框，不写执行库

    用法：
        #临时 买牛奶
        #任务 买牛奶 #临时        （修饰符形式，效果相同）
        #临时 交报告 【项目：项目A】【截止：2026/07/20】

    判定规则：带 #临时 标记 = 轻量任务 → 仅任务框；无标记 = 正式 → 执行库
    """
    # 提取结构化变量（可选：项目/优先级/截止）
    vars = extract_variables(raw_text)
    title = extract_main_content(raw_text).replace("#临时", "").strip()
    if not title:
        return {"ok": False, "type": "lightweight", "error": "⚠️ 未提取到任务标题，如：`#临时 买牛奶`"}

    # 截止时间（默认今天 23:59 全天，使其在今日任务框可见）
    due_ms = None
    if vars.get("截止日期"):
        try:
            dt = datetime.strptime(vars["截止日期"], "%Y/%m/%d")
            due_ms = str(int(dt.timestamp() * 1000 + 86399000))
        except ValueError:
            pass
    if not due_ms:
        dt = datetime.now()
        due_ms = str(int(dt.timestamp() * 1000 + 86399000))

    summary = f"[临时] {title}"
    desc_parts = ["类型：轻量任务（不写执行库）"]
    if vars.get("所属项目"):
        desc_parts.append(f"项目：{vars['所属项目']}")
    if vars.get("截止日期"):
        desc_parts.append(f"截止：{vars['截止日期']}")
    task_data = {
        "summary": summary,
        "description": " | ".join(desc_parts),
        "due": {"timestamp": due_ms, "is_all_day": True},
    }

    if dry_run:
        return {
            "ok": True, "dry_run": True, "type": "lightweight",
            "message": f"仅入任务框（不写执行库）\n  标题：{summary}\n  数据：{json.dumps(task_data, ensure_ascii=False)}",
        }

    # 实际创建到任务框
    tmp_name = f"_lt_task_{uuid.uuid4().hex[:8]}.json"
    tmp_path = os.path.join(os.getcwd(), tmp_name)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(task_data, ensure_ascii=False))
        args = ["task", "tasks", "create", "--data", f"@{tmp_name}", "--as", "user"]
        result = _run_lark_cli(args)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.returncode == 0:
        try:
            resp = json.loads(result.stdout)
            guid = resp.get("data", {}).get("task", {}).get("guid", "") or resp.get("data", {}).get("guid", "")
        except json.JSONDecodeError:
            guid = ""
        return {
            "ok": True, "type": "lightweight",
            "message": f"✅ 轻量任务已创建（仅任务框）：{summary}\n   📌 不写入执行库，每日排程不纳入；标题带 [临时] 前缀便于识别",
            "guid": guid,
        }
    return {"ok": False, "type": "lightweight", "error": f"创建失败：{result.stderr or result.stdout}"}
