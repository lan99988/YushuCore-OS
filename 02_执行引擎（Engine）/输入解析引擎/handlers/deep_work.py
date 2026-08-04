"""Deep work orchestrator handler (Step2-4-C-8c).

迁移自旧 monolith 的 handle_deep_work（深度工作通用入口），1:1 复刻二级分发逻辑。
作为深度工作域的 Orchestrator，直接调用同包内已迁移的
handlers.deep_plan / handlers.deep_record（不依赖冻结旧模块）。
"""

import re

from . import deep_plan, deep_record


def handle_deep_work(raw_text, dry_run=False):
    """处理 #深度 通用入口：自动判断是规划还是记录。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``。
    """
    content = raw_text.replace("#深度", "").strip()

    if not content:
        return {
            "ok": True,
            "type": "deep_info",
            "message": "🔴 【深度工作】\n"
                       "  · #深度规划 深度4小时 浮浅控制30% → 设定今日目标\n"
                       "  · #深度记录 深度3.5小时 心流高 干扰1次 → 记录表现\n"
                       "  · 标签【冲刺】→ 标记罗斯福冲刺任务\n"
                       "  · 标签【深度：7】→ 标记任务深度分(1-10)",
        }

    # 有数字+深度关键词 → 记录
    if re.search(r'深度\s*[\d.]+', content):
        return deep_record.handle_deep_record(raw_text, dry_run)

    # 有"规划"/"目标"/"预算" → 规划
    if any(k in content for k in ["规划", "目标", "预算", "h", "小时", "浮浅"]):
        return deep_plan.handle_deep_plan(raw_text, dry_run)

    # 有"心流"/"干扰"/"得分" → 记录
    if any(k in content for k in ["心流", "干扰", "得分", "备注"]):
        return deep_record.handle_deep_record(raw_text, dry_run)

    # 默认：展示帮助
    return {
        "ok": True,
        "type": "deep_info",
        "message": "🔴 深度工作指令参考\n使用 #深度规划 或 #深度记录",
    }
