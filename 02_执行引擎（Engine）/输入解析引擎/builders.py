"""
记录构建与输出格式化模块

迁移自 input_parser_old.py（原样搬运，逻辑 0 改动）：
build_record(table_name, title, vars, raw_text)  构建飞书记录字段字典
format_output(result)                            格式化用户可见输出文本

依赖说明：
- build_record 内部调用 extractor 的 5 个解析函数（财务/社交/创作/知识/标题清洗）。
- 日期字段（财务流水表/社交关系表）使用 datetime.now() 生成，原样保留。
- format_output 仅依赖 json，无外部状态。
"""

import json
from datetime import datetime

from .extractor import (
    parse_bill_vars,
    parse_social_vars,
    build_social_title,
    parse_create_vars,
    parse_knowledge_vars,
)


def build_record(table_name, title, vars, raw_text=""):
    """构建飞书记录JSON"""
    fields = {}

    if table_name == "执行库":
        fields = {
            "标题": title,
            "所属项目": vars.get("所属项目", ""),
            "轻重缓急": vars.get("轻重缓急", "P2-紧急不重要"),
            "状态": vars.get("状态", "待收集"),
            "截止日期": vars.get("截止日期"),
            "精力消耗等级": vars.get("精力消耗等级", "中"),
            "预估耗时": vars.get("预估耗时"),
            "是否为今日硬骨头": vars.get("是否为今日硬骨头", False),
        }
        # 责任人
        if "责任人" in vars:
            fields["责任人"] = vars["责任人"]
        # 自动推断科目类别（仅考研且有具体子科目时）
        if vars.get("所属项目") == "考研" and "科目类别" in vars:
            fields["科目类别"] = vars["科目类别"]
        # 🆕 冲刺任务标记写入标题
        if vars.get("是否为冲刺任务"):
            fields["标题"] = f"🔥 {title}"
            if not fields.get("预估耗时"):
                fields["预估耗时"] = 30
            fields["精力消耗等级"] = "高"

    elif table_name == "灵感库":
        fields = {
            "标题": title,
            "所属项目": vars.get("所属项目", ""),
            "轻重缓急": vars.get("轻重缓急", "P2-紧急不重要"),
            "状态": vars.get("状态", "待收集"),
            "灵感原文": vars.get("灵感原文", title),
            "触发场景": vars.get("触发场景", ""),
            "转化状态": "待孵化",
            "优先级预判": vars.get("轻重缓急", "P2-紧急不重要"),
        }
        if "责任人" in vars:
            fields["责任人"] = vars["责任人"]

    elif table_name == "Bug库":
        fields = {
            "标题": title,
            "所属项目": vars.get("所属项目", ""),
            "轻重缓急": vars.get("轻重缓急", "P2-紧急不重要"),
            "状态": vars.get("状态", "待收集"),
            "Bug简述": vars.get("Bug简述", title),
            "严重程度": vars.get("严重程度", "功能缺陷"),
            "修复状态": "待修复",
        }
        if "责任人" in vars:
            fields["责任人"] = vars["责任人"]

    elif table_name == "财务流水表":
        bill_vars = parse_bill_vars(raw_text)
        fields = {
            "标题": title,
            "金额": bill_vars.get("金额"),
            "类型": bill_vars.get("类型", "支出"),
            "分类": bill_vars.get("分类", "其他"),
            "日期": datetime.now().strftime("%Y/%m/%d"),
        }
        if bill_vars.get("金额") is None:
            print("⚠️ [财务] 未提取到金额，请确认输入包含数字+元/块")
            print("  示例：#账单 午饭 28元 餐饮")

    elif table_name == "社交关系表":
        social_vars = parse_social_vars(raw_text)
        social_title_clean = build_social_title(raw_text)
        # 提取联系人：取第一个词，"见了张三"→"张三"
        contact_raw = social_title_clean.split(" ")[0] if " " in social_title_clean else social_title_clean
        # 去掉常见动词前缀
        contact = contact_raw
        for verb in ["见了", "见", "和", "给", "跟", "约了", "找"]:
            if contact_raw.startswith(verb):
                contact = contact_raw[len(verb):]
                break
        # 再去掉残留的"和"或"微信"前缀
        for prefix in ["和", "微信", "微信和"]:
            if contact.startswith(prefix):
                contact = contact[len(prefix):]
                break
        # 如果在电话/微信等场景中，去掉动作词
        for suffix in ["打电话", "发微信", "发消息", "聊天", "通电话", "视频"]:
            if contact.endswith(suffix):
                contact = contact[:-len(suffix)]
                break
        fields = {
            "标题": social_title_clean[:100] if social_title_clean else title,
            "联系人": contact if contact else title,
            "活动类型": social_vars.get("活动类型", "其他"),
            "活动内容": title,
            "亲密度": social_vars.get("亲密度", "★★"),
            "日期": datetime.now().strftime("%Y/%m/%d"),
        }
        # 如果有生日信息，写入生日字段
        if social_vars.get("_has_birthday"):
            fields["生日"] = social_vars["生日"]
        # 如果有关系标签
        if social_vars.get("关系标签"):
            fields["关系标签"] = social_vars["关系标签"]

    elif table_name == "创作素材表":
        create_vars = parse_create_vars(raw_text)
        fields = {
            "标题": title,
            "类型": create_vars.get("类型", "文章"),
            "状态": create_vars.get("状态", "灵感"),
            "内容摘要": title,
        }
        if create_vars.get("关联灵感"):
            fields["关联灵感"] = create_vars["关联灵感"]

    elif table_name == "知识笔记表":
        know_vars = parse_knowledge_vars(raw_text)
        fields = {
            "标题": title,
            "知识点": title,
            "类型": know_vars.get("类型", "常青笔记"),
            "分类": know_vars.get("分类", "其他"),
            "来源": know_vars.get("来源", "其他"),
            "来源详情": know_vars.get("来源详情", ""),
        }
        if know_vars.get("关联记录"):
            fields["关联记录"] = know_vars["关联记录"]
        if know_vars.get("关联灵感"):
            fields["关联灵感"] = know_vars["关联灵感"]

    return fields


def format_output(result):
    """格式化输出结果"""
    if not result.get("ok"):
        return f"[失败] {result.get('error', '未知错误')}"

    if result.get("type") == "energy_status":
        msg = result["message"]
        if result.get("suggestion"):
            msg += f"\n[建议] {result['suggestion']}"
        return f"[OK] {msg}"

    if result.get("type") == "hatch":
        if result.get("dry_run"):
            payload = result.get("payload", {})
            return (
                f"[TEST] 目标表：{result['table']}\n"
                f"  灵感来源：{result.get('source', {}).get('标题', '')}\n"
                f"  记录内容：\n"
                f"  {json.dumps(payload, ensure_ascii=False, indent=2)}"
            )
        return f"[OK] {result['message']}"

    if result.get("type") == "review":
        return f"[复盘]\n{result['message']}"

    if result.get("type") == "config":
        configs = result.get("configs", {})
        if configs:
            items = "\n".join(f"  . {k} = {v}" for k, v in configs.items())
            return f"[OK] 配置已解析：\n{items}"
        return "[WARN] 未识别到有效的配置项"

    if result.get("type") == "calendar":
        if result.get("dry_run"):
            return f"[TEST-日历]\n{result['message']}"
        return f"[日历]\n{result['message']}"

    if result.get("type") in ("deep_plan", "deep_record", "deep_info"):
        return f"[深度工作]\n{result['message']}"

    if result.get("type") == "deep_review":
        return f"[深度复盘]\n{result['message']}"

    if result.get("type") == "attention_audit":
        return f"[注意力审计]\n{result['message']}"

    if result.get("type") == "lightweight":
        if result.get("dry_run"):
            return f"[TEST-临时]\n{result['message']}"
        if result.get("error"):
            return f"[轻量任务] ❌ {result['error']}"
        return f"[轻量任务]\n{result['message']}"

    if result.get("type") == "sync_taskbox":
        if result.get("dry_run"):
            return f"[TEST-同步任务框]\n{result['message']}"
        if result.get("error"):
            return f"[同步任务框] ❌ {result['error']}"
        return f"[同步任务框]\n{result['message']}"

    if result.get("type") in ("habit_create", "habit_checkin", "habit_list", "habit_progress", "habit_help"):
        return f"[习惯]\n{result['message']}"

    if result.get("type") in ("habit_error",):
        return f"[习惯] {result.get('message', result.get('error', '未知错误'))}"

    if result.get("type") in ("competition", "competition_detail"):
        return f"[比赛]\n{result['message']}"

    if result.get("deduplicated"):
        return f"[去重] 任务已存在，跳过创建：{result.get('title', '')}"

    if result.get("dry_run"):
        payload = result.get("payload", {})
        return (
            f"[TEST] 目标表：{result['table']}\n"
            f"  记录内容：\n"
            f"  {json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    table_name = result.get("table", "")
    return f"[OK] 已写入 [{table_name}]"
