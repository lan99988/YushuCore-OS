"""
#注意力审计 handler

迁移来源：input_parser_old.py handle_attention_audit (行 1678-1724)
原则：1:1 复刻业务逻辑，零行为差。仅做变量重命名（text→raw_text）。

职责：三步倒推法审视注意力分配，纯本地文本生成。
无网络 / 无文件写入 / 无外部模块依赖 / 不需要任何 import。
"""


def handle_attention_audit(raw_text, dry_run=False):
    """处理 #注意力审计 指令：三步倒推法审视注意力分配

    用法：
        #注意力审计           → 开始三步倒推流程
        #注意力审计 目标1 考研 目标2 公众号
    """
    content = raw_text.replace("#注意力审计", "").strip()

    report = []
    report.append("🔍 【注意力经济审计】三步倒推法")
    report.append("")
    report.append("你不是在「使用」社交媒体，")
    report.append("你是被1000个人设计的产品劫持的注意力资源。")
    report.append("")
    report.append("━━ 第一步：你最重要的2-4个目标是什么？ ━━")
    if content:
        # 用户已提供目标
        goals = [g.strip() for g in content.split("目标") if g.strip()]
        if not goals:
            goals = [content]
        for i, g in enumerate(goals, 1):
            report.append(f"  目标{i}：{g}")
    else:
        report.append("  （请列出你最重要的2-4个目标）")
    report.append("")
    report.append("━━ 第二步：每个目标下，最重要的2-3个日常活动是什么？ ━━")
    report.append("  （对每个目标，写出支撑它的核心日常活动）")
    report.append("")
    report.append("━━ 第三步：实现这些活动的最佳途径是社交媒体吗？ ━━")
    report.append("  · 如果是 → 保留，但设定时间边界")
    report.append("  · 如果不是 → 考虑戒断或大幅减少")
    report.append("")
    report.append("📊 评估标准：")
    report.append("  · 每个社交媒体工具，对核心目标有实质性帮助吗？")
    report.append("  · 你能控制使用时长，还是被它控制？")
    report.append("  · 30天戒断测试：停用30天，生活变差了吗？")
    report.append("")
    report.append("💡 核心认知转换：")
    report.append("  · 工具选择应该是「主动」而非「默认」")
    report.append("  · 不要用「有任何好处」来辩护，要用「比替代方案好多少」来判断")

    return {
        "ok": True,
        "type": "attention_audit",
        "message": "\n".join(report),
    }
