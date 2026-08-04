"""
#孵化 handler

迁移来源：input_parser_old.py handle_hatch (行 1000-1091)
原则：1:1 复刻业务逻辑，零行为差。仅做 import 调整与变量重命名。

职责：从灵感库筛选「待孵化」灵感 → 转为执行库任务 → 更新灵感转化状态。
依赖：config(BASE_TOKEN/TABLES) / lark_bridge(_run_lark_cli) / feishu_write(insert_to_feishu)。
无本地 runtime 文件写入，无 junction 路径风险。
"""

import json

from ..config import BASE_TOKEN, TABLES
from ..lark_bridge import _run_lark_cli
from ..feishu_write import insert_to_feishu


def handle_hatch(raw_text, dry_run=False):
    """处理 #孵化 指令：从灵感库选取待孵化灵感转为执行库任务

    用法：
        #孵化                → 随机取第一条待孵化灵感转为任务
        #孵化 数学二          → 选取匹配的数学二灵感转为任务
    """
    # 可选：指定科目筛选
    project_filter = None
    content = raw_text.replace("#孵化", "").strip()
    if content:
        project_filter = content

    # 查询灵感库
    args = [
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["灵感库"],
        "--as", "user",
        "--limit", "50",
        "--format", "json",
    ]
    result = _run_lark_cli(args)

    if result.returncode != 0:
        return {"ok": False, "error": "读取灵感库失败"}

    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])

        # 筛选待孵化灵感
        candidates = []
        for row in data_array:
            fields = dict(zip(field_names, row))
            if fields.get("转化状态") != "待孵化":
                continue
            # 可选科目过滤
            if project_filter and project_filter not in fields.get("所属项目", ""):
                continue
            candidates.append(fields)

        if not candidates:
            return {"ok": True, "message": "灵感库中没有待孵化的灵感"}

        # 取最新的一条
        idea = candidates[0]
        title = idea.get("标题", "未命名灵感")

        # 构建执行库任务
        task_fields = {
            "标题": f"[灵感孵化] {title}",
            "所属项目": idea.get("所属项目", ""),
            "轻重缓急": idea.get("优先级预判", "P2-紧急不重要"),
            "状态": "待收集",
            "精力消耗等级": "中",
            "预估耗时": 60,  # 默认60分钟
        }

        if dry_run:
            return {
                "ok": True, "dry_run": True, "table": "执行库",
                "payload": task_fields,
                "source": idea,
            }

        # 写入执行库
        insert_to_feishu("执行库", task_fields)

        # 更新灵感库转化状态
        idea_id = idea.get("record_id", idea.get("id", ""))
        if idea_id:
            update_args = [
                "base", "+record-update",
                "--base-token", BASE_TOKEN,
                "--table-id", TABLES["灵感库"],
                "--record-id", idea_id,
                "--json", '{"转化状态": "已孵化"}',
                "--as", "user",
            ]
            _run_lark_cli(update_args)

        return {
            "ok": True,
            "type": "hatch",
            "message": f"已孵化灵感 → 创建任务：'{title}'",
            "details": task_fields,
        }
    except (json.JSONDecodeError, KeyError):
        return {"ok": False, "error": "解析灵感库数据失败"}
