"""
#同步任务框 handler

迁移来源：input_parser_old.py handle_sync_taskbox (行 2126-2246) + _sync_taskbox_report (2249-2259)
原则：1:1 复刻业务逻辑，零行为差。仅做 import 调整与变量重命名（text→raw_text）。

职责：扫描飞书任务框「我负责的任务」→ 分类（临时/已完成/已同步/待入库）→ 正式任务入库执行库。
依赖：config(BASE_TOKEN/TABLES) / lark_bridge(_run_lark_cli) / feishu_write(insert_to_feishu) / 标准库 json+datetime。
注意：insert_to_feishu 必须带 target_date= 与 dry_run=False（触发去重），不可改动。
"""

import json
from datetime import datetime

from ..config import BASE_TOKEN, TABLES
from ..lark_bridge import _run_lark_cli
from ..feishu_write import insert_to_feishu


def _sync_taskbox_report(temp_skip, done_skip, already_synced, to_sync):
    lines = ["📥 【任务框 → 执行库 同步预览】"]
    lines.append(f"  · 轻量任务（带[临时]，跳过不入库）：{len(temp_skip)} 个")
    for s in temp_skip[:10]:
        lines.append(f"      - {s}")
    lines.append(f"  · 已完成任务（跳过）：{len(done_skip)} 个")
    lines.append(f"  · 已同步正式任务（跳过）：{len(already_synced)} 个")
    lines.append(f"  · 待入库正式任务：{len(to_sync)} 个")
    for t in to_sync[:20]:
        lines.append(f"      + {t['summary']}（截止 {t['deadline']}）")
    return "\n".join(lines)


def handle_sync_taskbox(raw_text, dry_run=False):
    """处理 #同步任务框 指令：扫描飞书任务框，将未入库的正式任务拉回执行库

    分类规则：
        [临时] 前缀      → 轻量任务，跳过（不入库）
        status == done   → 已完成，跳过
        标题已在执行库    → 已同步正式任务，跳过
        其余（无前缀/未完成/未入库）→ 正式任务，待入库

    用法：
        #同步任务框           → 扫描并预览/同步
        #同步任务框 --dry-run  → 仅预览，不写执行库
    """
    # 1. 拉取任务框所有任务（我负责的）
    result = _run_lark_cli([
        "task", "tasks", "list",
        "--type", "my_tasks",
        "--page-size", "100",
        "--page-all",
        "--format", "json",
        "--as", "user",
    ])
    if result.returncode != 0:
        return {"ok": False, "type": "sync_taskbox", "error": f"读取任务框失败：{result.stderr or result.stdout}"}
    try:
        resp = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "type": "sync_taskbox", "error": "解析任务框数据失败"}

    items = resp.get("data", {}).get("items", [])

    # 2. 拉取执行库已有标题集合（用于去重判定）
    base_titles = set()
    offset = 0
    while True:
        base_args = [
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLES["执行库"],
            "--as", "user",
            "--limit", "200",
            "--offset", str(offset),
            "--format", "json",
        ]
        base_result = _run_lark_cli(base_args)
        if base_result.returncode != 0:
            return {"ok": False, "type": "sync_taskbox",
                    "error": f"读取执行库失败：{base_result.stderr or base_result.stdout}"}
        try:
            bd = json.loads(base_result.stdout).get("data", {})
        except json.JSONDecodeError:
            return {"ok": False, "type": "sync_taskbox", "error": "解析执行库数据失败"}
        bfields = bd.get("fields", [])
        bdata = bd.get("data", [])
        for row in bdata:
            f = dict(zip(bfields, row))
            t = f.get("标题")
            if isinstance(t, list):
                t = t[0] if t else None
            if t:
                base_titles.add(str(t))
        if not bd.get("has_more"):
            break
        offset += 200
        if offset > 10000:  # 安全阀
            break

    # 3. 分类
    temp_skip, done_skip, already_synced, to_sync = [], [], [], []
    for it in items:
        summary = it.get("summary", "")
        status = it.get("status", "")
        if summary.startswith("[临时]"):
            temp_skip.append(summary)
            continue
        if status == "done":
            done_skip.append(summary)
            continue
        if summary in base_titles:
            already_synced.append(summary)
            continue
        # 解析截止日期（来自任务框 due.timestamp）
        due = it.get("due", {}) or {}
        due_ms = due.get("timestamp")
        deadline = None
        if due_ms:
            try:
                deadline = datetime.fromtimestamp(int(due_ms) / 1000).strftime("%Y/%m/%d")
            except (ValueError, OSError, OverflowError):
                deadline = None
        if not deadline:
            deadline = datetime.now().strftime("%Y/%m/%d")
        to_sync.append({"summary": summary, "deadline": deadline, "description": it.get("description", "")})

    # 4. 执行 or 预览
    if dry_run:
        return {
            "ok": True, "dry_run": True, "type": "sync_taskbox",
            "message": _sync_taskbox_report(temp_skip, done_skip, already_synced, to_sync),
            "to_sync": to_sync,
        }

    created = []
    for t in to_sync:
        fields = {
            "标题": t["summary"],
            "轻重缓急": "P3-不重要不紧急",
            "状态": "待收集",
            "截止日期": t["deadline"],
            "精力消耗等级": "中",
            "预估耗时": 30,
        }
        res = insert_to_feishu("执行库", fields, target_date=t["deadline"], dry_run=False)
        if res.get("ok") and not res.get("deduplicated"):
            created.append(t["summary"])

    msg = _sync_taskbox_report(temp_skip, done_skip, already_synced, to_sync)
    msg += f"\n\n✅ 已同步 {len(created)} 个正式任务到执行库"
    if created:
        msg += "\n" + "\n".join(f"  · {c}" for c in created)
    return {"ok": True, "type": "sync_taskbox", "message": msg, "created": created}
