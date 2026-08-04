"""
输入解析层

未来迁移（本阶段已落地）：
detect_prefix      输入前缀识别，返回 (表名, 剩余文本)
extract_variables  从文本提取结构化变量
extract_main_content 去除标记后的纯文本
parse_date         多种日期格式 → yyyy/MM/dd
auto_detect_category 按项目推断科目类别

本模块为纯函数层：不依赖飞书、不依赖外部状态。
常量统一来自 .config，逻辑与 input_parser_old 完全一致。
"""

import re
from datetime import datetime

from .config import PREFIX_MAP, PROJECT_ALIAS, PRIORITY_MAP


def detect_prefix(text):
    """检测前缀指令，返回 (table_name, remaining_text)"""
    for prefix, table in sorted(PREFIX_MAP.items(), key=lambda x: -len(x[0])):
        if text.strip().startswith(prefix):
            return table, text.strip()[len(prefix):].strip()
    return None, text.strip()


def extract_variables(text):
    """从文本中提取所有结构化变量"""
    vars = {}

    # 1. 提取 【项目：XXX】
    m = re.search(r'【项目[：:]\s*(.+?)】', text)
    if m:
        raw = m.group(1).strip()
        vars["所属项目"] = PROJECT_ALIAS.get(raw, raw)

    # 2. 提取 #项目名（如 #数学二 #项目A #生活区 #全局）
    project_pattern = '|'.join(re.escape(k) for k in sorted(PROJECT_ALIAS.keys(), key=len, reverse=True))
    m = re.search(f'#({project_pattern})', text)
    if m and "所属项目" not in vars:
        raw = m.group(1)
        vars["所属项目"] = PROJECT_ALIAS.get(raw, raw)

    # 自动推断科目类别（仅当所属项目=考研且有具体子科目时）
    if vars.get("所属项目") == "考研":
        # 检查输入中是否包含具体科目名
        for subj, cat in [("数学二", "数学"), ("英语二", "英语"), ("政治", "政治"), ("408", "专业课")]:
            if subj in text:
                vars["科目类别"] = cat
                break

    # 3. 提取轻重缓急
    for tag, priority in PRIORITY_MAP.items():
        if tag in text:
            vars["轻重缓急"] = priority
            break
    if "轻重缓急" not in vars and re.search(r'【紧急[：:].*?】', text):
        vars["轻重缓急"] = "P0-重要紧急"
    if "轻重缓急" not in vars:
        vars["轻重缓急"] = "P2-紧急不重要"  # 默认

    # 4. 提取截止日期
    # 格式：2026/07/05 或 7月5日
    m = re.search(r'【截止[：:]\s*(.+?)】', text)
    if m:
        date_str = m.group(1).strip()
        vars["截止日期"] = parse_date(date_str)

    # 5. 提取精力消耗等级
    m = re.search(r'【精力[：:]\s*(高|中|低)】', text)
    if m:
        vars["精力消耗等级"] = m.group(1)
    else:
        # 检查 #高/#中/#低 标签
        for level in ["高", "中", "低"]:
            if f"#{level}" in text:
                vars["精力消耗等级"] = level
                break
    if "精力消耗等级" not in vars:
        vars["精力消耗等级"] = "中"  # 默认

    # 6. 提取预估耗时
    m = re.search(r'【耗时[：:]\s*(\d+)\s*分钟?】', text)
    if m:
        vars["预估耗时"] = int(m.group(1))
    else:
        m = re.search(r'(\d+)\s*分钟', text)
        if m:
            vars["预估耗时"] = int(m.group(1))

    # 7. 检测硬骨头 — 统一标记风格（支持"【硬骨头】"、"#硬骨头"两种格式）
    vars["是否为今日硬骨头"] = ("【硬骨头】" in text) or ("#硬骨头" in text) or ("【硬骨】" in text)

    # 🆕 8. 检测罗斯福冲刺标记
    vars["是否为冲刺任务"] = "【冲刺】" in text
    # 冲刺任务：默认为高精力、30分钟
    if vars.get("是否为冲刺任务"):
        if "预估耗时" not in vars:
            vars["预估耗时"] = 30
        if vars.get("精力消耗等级", "中") == "中":
            vars["精力消耗等级"] = "高"

    # 🆕 9. 检测深度分标记 【深度：N】
    m = re.search(r'【深度[：:]\s*(\d+)】', text)
    if m:
        score = int(m.group(1))
        vars["深度分"] = max(1, min(10, score))  # 限制1-10

    # 8. 提取触发场景（灵感库专用）
    m = re.search(r'【触发场景[：:]\s*(.+?)】', text)
    if m:
        vars["触发场景"] = m.group(1).strip()

    # 9. 提取严重程度（Bug库专用）
    m = re.search(r'【严重程度[：:]\s*(崩溃|功能缺陷|UI优化)】', text)
    if m:
        vars["严重程度"] = m.group(1)

    # 10. 提取Bug简述/灵感原文（括号外剩余文本是主要内容）
    # 去除所有【】标记后剩余的部分作为主要描述

    # 11. 提取责任人【责任人：XXX】
    m = re.search(r'【责任人[：:]\s*(.+?)】', text)
    if m:
        raw = m.group(1).strip()
        # 映射到select选项
        agent_map = {
            "我自己": "我自己", "我": "我自己", "自": "我自己",
            "workbuddy": "WorkBuddy", "WorkBuddy": "WorkBuddy", "WB": "WorkBuddy",
            "随手录": "随手录", "随手": "随手录",
            "其他": "其他Agent", "other": "其他Agent",
        }
        vars["责任人"] = agent_map.get(raw, raw)

    return vars


def parse_date(date_str):
    """解析各种日期格式为 yyyy/MM/dd"""
    # 尝试 yyyy/MM/dd 或 yyyy-MM-dd
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    # 尝试 MM月dd日
    m = re.search(r'(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        now = datetime.now()
        year = now.year
        month = int(m.group(1))
        day = int(m.group(2))
        # 如果月份已过，默认明年
        if month < now.month:
            year += 1
        return f"{year}/{month:02d}/{day:02d}"
    # 尝试 dd日
    m = re.search(r'(\d{1,2})日', date_str)
    if m:
        now = datetime.now()
        day = int(m.group(1))
        if day >= now.day:
            return f"{now.year}/{now.month:02d}/{day:02d}"
        else:
            next_month = now.month + 1
            year = now.year
            if next_month > 12:
                next_month = 1
                year += 1
            return f"{year}/{next_month:02d}/{day:02d}"
    return None


def extract_main_content(text):
    """提取主要描述内容（去除所有标记后的纯文本）"""
    # 去除 #任务/#灵感/#Bug 前缀
    for prefix in PREFIX_MAP:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    # 去除所有【】标记
    text = re.sub(r'【[^】]*?】', '', text)
    # 去除 #项目名 等标签
    text = re.sub(r'#[^\s]*', '', text)
    # 清理多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def auto_detect_category(project):
    """根据所属项目自动推断科目类别（仅考研需要）"""
    if project == "考研":
        return None  # 由具体输入决定
    return None
