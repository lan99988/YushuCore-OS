"""Deep plan handler (Step2-4-C-8a).

迁移自 input_parser_old.handle_deep_plan（1363-1416），1:1 复刻业务逻辑。
本文件只委托标准库（re/os/json/datetime），不依赖其他已迁移模块、无网络调用。
"""

import os
import re
import json
from datetime import datetime


def _engine_runtime_path():
    """复刻旧 main 的 ``os.path.dirname(__file__)`` 语义（关键路径保护）。

    旧代码位于 ``输入解析引擎/`` 根，故用 ``dirname(__file__)`` 得到引擎根，
    再拼 ``runtime/_deep_work_plan.json``（该 ``runtime`` 是 junction，
    指向共享 ``04_数据中心/运行状态（Runtime）``）。

    本 handler 位于 ``输入解析引擎/handlers/``，若直接用 ``dirname(__file__)``
    会错误落到 ``handlers/runtime/``（非 junction，每日排程引擎读不到）。
    因此须上溯两级回到引擎根，保持与旧代码**逐字一致**的物理写入目标。
    """
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_dir, "runtime", "_deep_work_plan.json")


def handle_deep_plan(raw_text, dry_run=False):
    """处理 #深度规划 指令：设定当天深度工作目标。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``；dry_run 旧逻辑无分支，故忽略
    （与旧 ``_call_deep_plan`` 透传一致，不引入 dry_run 行为差）。
    """
    content = raw_text.replace("#深度规划", "").strip()

    # 解析深度时间
    deep_hours = None
    m = re.search(r'深度\s*(\d+\.?\d*)\s*h(?:ours?|r)?', content, re.IGNORECASE)
    if m:
        deep_hours = float(m.group(1))
    m = re.search(r'深度\s*(\d+\.?\d*)\s*小时', content)
    if m:
        deep_hours = float(m.group(1))

    # 解析浮浅预算
    shallow_pct = 30  # 默认30%
    m = re.search(r'浮浅\s*(?:控制|不超过|少于)?\s*(\d+)%', content)
    if m:
        shallow_pct = min(100, max(0, int(m.group(1))))
    m = re.search(r'浮浅\s*(\d+\.?\d*)\s*h(?:ours?|r)?', content, re.IGNORECASE)
    if m:
        shallow_hours = float(m.group(1))
        if deep_hours:
            total = deep_hours + shallow_hours
            shallow_pct = min(100, max(0, int(shallow_hours / total * 100)))

    # 保存规划到配置文件
    plan_data = {
        "deep_work_hours_target": deep_hours,
        "shallow_work_budget_pct": shallow_pct,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    plan_file = _engine_runtime_path()
    try:
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan_data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass

    msg_parts = []
    if deep_hours:
        msg_parts.append(f"🎯 深度工作目标：{deep_hours}h")
    msg_parts.append(f"📊 浮浅工作预算：≤{shallow_pct}%")

    return {
        "ok": True,
        "type": "deep_plan",
        "message": " | ".join(msg_parts) if msg_parts else "深度规划已保存",
        "plan": plan_data,
    }
