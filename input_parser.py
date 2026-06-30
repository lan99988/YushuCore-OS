#!/usr/bin/env python3
"""
个人混合管理系统 - 输入解析引擎
===================================
解析微信/WorkBuddy消息，提取指令和变量，写入飞书多维表格。

用法：
    python input_parser.py "#任务 做数学真题2010 【项目：数学二】【精力：高】【耗时：120分钟】【截止：2026/07/05】"
    python input_parser.py "#灵感 想到一个笔记方法 【项目：408】【触发场景：洗澡时】"
    python input_parser.py "#Bug 页面崩溃 【项目：项目A】【严重程度：崩溃】"
    python input_parser.py "#精力 今天状态很差"
    python input_parser.py "#配置 黄金段 08:30-11:30"
    python input_parser.py "#账单 午饭 28元 餐饮"
    python input_parser.py "#社交 见了张三 聊考研 同学 ★★★"
    python input_parser.py "#创作 公众号文章 文章 灵感"
    python input_parser.py "#知识 泰勒公式展开 数学 来源:张宇P120"

测试模式（不写入）：
    python input_parser.py --dry-run "#任务 测试任务"
"""

import re
import json
import subprocess
import sys
import os
from datetime import datetime, timedelta

# ============ 配置 ============
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
# lark-cli 路径（Windows下需要通过bash执行shell包装器）
LARK_CLI_SCRIPT = r"C:\Users\26326\.workbuddy\binaries\node\cli-connector-packages\lark-cli"
# 检测是否可以通过直接调用运行
import shutil
LARK_CLI = shutil.which("lark-cli") if shutil.which("lark-cli") else (
    LARK_CLI_SCRIPT if os.path.isfile(LARK_CLI_SCRIPT) else "lark-cli"
)

# 表名 → table_id 映射
TABLES = {
    "执行库": "tblNQCB4pn6Rso4a",
    "灵感库": "tblx1ZaQGwXvoJhj",
    "Bug库": "tblPpPputYMACtQ5",
    "科目进度基线": "tblQnjCO03WjQ7GC",
    "财务流水表": "tblPFKBGubeIYsfm",
    "社交关系表": "tblt7uTkIcLhH7bs",
    "创作素材表": "tbl99pDAlTIDu7f5",
    "知识笔记表": "tblgtdx4h0EJjRrh",
}

# 前缀 → 目标表
PREFIX_MAP = {
    "#任务": "执行库",
    "#灵感": "灵感库",
    "#Bug": "Bug库",
    "#精力": None,  # 特殊处理
    "#配置": None,  # 特殊处理
    "#账单": "财务流水表",
    "#财务": "财务流水表",
    "#社交": "社交关系表",
    "#关系": "社交关系表",
    "#人脉": "社交关系表",
    "#创作": "创作素材表",
    "#作品": "创作素材表",
    "#知识": "知识笔记表",
    "#笔记": "知识笔记表",
    "#学": "知识笔记表",
    "#孵化": None,  # 特殊处理：灵感→任务转化
    "#复盘": None,  # 特殊处理：回顾统计
}

# 项目→科目类别映射（仅考研有效）
SUBJECT_CATEGORY = {
    "数学二": "数学",
    "英语二": "英语",
    "政治": "政治",
    "408": "专业课",
    "考研": None,  # 考研本身不映射科目，由子科目决定
}

# 项目名简写映射
PROJECT_ALIAS = {
    "数学二": "考研",
    "英语二": "考研",
    "政治": "考研",
    "408": "考研",
    "项目A": "项目A",
    "项目B": "项目B",
    "项目C": "项目C",
    "项目D": "项目D",
    "生活区": "生活区",
    "全局": "全局",
}

# 标签→轻重缓急映射
PRIORITY_MAP = {
    "#P0": "P0-重要紧急",
    "#P1": "P1-重要不紧急",
    "#P2": "P2-紧急不重要",
    "#P3": "P3-不重要不紧急",
    "【紧急】": "P0-重要紧急",
    "【重要】": "P1-重要不紧急",
}


# ============ 解析引擎 ============

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


def parse_bill_vars(text):
    """解析 #账单/#财务 指令，提取财务变量"""
    vars = {}
    
    # 提取金额：数字（支持"28""50块""12.5"等）
    m = re.search(r'(\d+\.?\d*)\s*(元|块|¥|\$)?', text)
    if m:
        amount = float(m.group(1))
        vars["金额"] = amount
    else:
        vars["金额"] = None  # 标记为无效
    
    # 判断收入/支出（遵循Blueprint表5约定：正数=支出，负数=收入）
    if "收入" in text or "赚" in text or "工资" in text or "兼职" in text:
        vars["类型"] = "收入"
        if "金额" in vars and vars["金额"] is not None:
            vars["金额"] = -abs(vars["金额"])  # 收入存负数
    else:
        vars["类型"] = "支出"
        if "金额" in vars and vars["金额"] is not None:
            vars["金额"] = abs(vars["金额"])  # 支出行正数
    
    # 分类匹配
    category_map = {
        "饭": "餐饮", "餐": "餐饮", "吃": "餐饮", "食": "餐饮",
        "车": "交通", "行": "交通", "加油": "交通",
        "书": "学习", "课": "学习", "学": "学习",
        "衣服": "购物", "淘宝": "购物", "买": "购物",
        "电影": "娱乐", "游戏": "娱乐", "玩": "娱乐",
        "药": "医疗", "医院": "医疗",
        "聚会": "社交", "请客": "社交",
    }
    for keyword, cat in category_map.items():
        if keyword in text:
            vars["分类"] = cat
            break
    if "分类" not in vars:
        vars["分类"] = "其他"
    
    return vars


def parse_social_vars(text):
    """解析 #社交/#关系/#人脉 指令，提取社交变量"""
    vars = {}
    
    # 提取亲密度
    intimacy_map = {"★★★": "★★★", "★★": "★★", "★": "★"}
    for k, v in intimacy_map.items():
        if k in text:
            vars["亲密度"] = v
            break
    if "亲密度" not in vars:
        vars["亲密度"] = "★★"
    
    # 提取生日
    m = re.search(r'生日[：:]?\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if m:
        vars["生日"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        vars["_has_birthday"] = True
    
    # 活动类型推断（优先精确匹配后模糊匹配）
    if any(k in text for k in ["打电话", "打给", "打视频", "通电话"]):
        vars["活动类型"] = "电话"
    elif any(k in text for k in ["微信", "发消息"]):
        vars["活动类型"] = "微信聊天"
    elif any(k in text for k in ["吃饭", "饭局", "聚餐", "请客"]):
        vars["活动类型"] = "饭局"
    elif any(k in text for k in ["见面", "碰面", "约", "见了", "聚会"]):
        vars["活动类型"] = "见面"
    elif "活动" in text:
        vars["活动类型"] = "活动"
    else:
        vars["活动类型"] = "其他"
    
    # 关系标签推断
    tag_map = {
        "同学": "同学", "朋友": "朋友", "家人": "家人",
        "同事": "同事", "学长": "学长", "学弟": "学长",
        "学姐": "学长", "学妹": "学长", "合作伙伴": "合作伙伴",
        "合作": "合作伙伴",
    }
    for keyword, tag in tag_map.items():
        if keyword in text:
            vars["关系标签"] = [tag]
            break
    
    return vars


def parse_create_vars(text):
    """解析 #创作/#作品 指令，提取创作变量"""
    vars = {}
    
    # 状态提取
    status_map = {"灵感": "灵感", "草稿": "草稿", "进行中": "进行中", "已完成": "已完成", "已发布": "已发布"}
    for k, v in status_map.items():
        if k in text:
            vars["状态"] = v
            break
    if "状态" not in vars:
        vars["状态"] = "灵感"
    
    # 类型提取
    type_map = {"文章": "文章", "代码": "代码", "视频": "视频", "图片": "图片", "设计": "设计", "文档": "文档", "其他": "其他"}
    for k, v in type_map.items():
        if k in text:
            vars["类型"] = v
            break
    if "类型" not in vars:
        vars["类型"] = "文章"
    
    # 关联灵感
    m = re.search(r'关联灵感[：:]?\s*(.+?)(?:\s|$)', text)
    if m:
        vars["关联灵感"] = m.group(1).strip()
    
    return vars


def parse_knowledge_vars(text):
    """解析 #知识/#笔记/#学 指令，提取知识变量"""
    vars = {}
    
    # 提取来源详情
    m = re.search(r'来源[：:]?\s*(.+?)(?:\s关联[：:]\s*|$)', text)
    if m:
        source_detail = m.group(1).strip()
        vars["来源详情"] = source_detail
    
    # 来源类型匹配
    source_map = {
        "书": "书籍", "书籍": "书籍", "课程": "课程", "课": "课程",
        "文章": "文章", "视频": "视频", "经验": "经验",
        "AI": "AI对话", "ai": "AI对话",
    }
    for keyword, source in source_map.items():
        if keyword in vars.get("来源详情", "") or keyword in text:
            vars["来源"] = source
            break
    if "来源" not in vars:
        vars["来源"] = "其他"
    
    # 分类提取
    category_map = {
        "数学": "数学", "英语": "英语", "政治": "政治",
        "408": "408", "编程": "编程", "管理": "管理", "生活": "生活",
    }
    for keyword, cat in category_map.items():
        if keyword in text:
            vars["分类"] = cat
            break
    if "分类" not in vars:
        vars["分类"] = "其他"
    
    # MOC检测
    if "MOC" in text or "moc" in text:
        vars["类型"] = "MOC"
    else:
        vars["类型"] = "常青笔记"
    
    # 关联记录
    m = re.search(r'关联[：:]?\s*(.+?)(?:\s|$)', text)
    if m:
        # 过滤掉"关联灵感"开头的
        rel_text = m.group(1).strip()
        if not rel_text.startswith("灵感"):
            vars["关联记录"] = rel_text
    
    # 关联灵感（知识专用）
    m = re.search(r'关联灵感[：:]?\s*(.+?)(?:\s|$)', text)
    if m:
        vars["关联灵感"] = m.group(1).strip()
    
    return vars


def build_social_title(text):
    """根据知识笔记表的创建时间和分类，推断各科完成率建议值
    
    返回: {"数学": 15.2, "英语": 8.5, "政治": 3.0, "专业课": 12.1}
    """
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["知识笔记表"],
        "--as", "user",
        "--limit", "200",
        "--format", "json",
    ])
    
    if result.returncode != 0:
        return {}
    
    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        
        # 按分类统计最近30天的笔记数量
        now = datetime.now()
        category_counts = {}
        for row in data_array:
            fields = dict(zip(field_names, row))
            cat = fields.get("分类", "")
            created = fields.get("创建时间", "")
            if not created or not cat:
                continue
            try:
                created_str = str(created)[:10]
                created_date = datetime.strptime(created_str, "%Y-%m-%d")
                if (now - created_date).days <= 30:
                    category_counts[cat] = category_counts.get(cat, 0) + 1
            except ValueError:
                continue
        
        # 转换为建议完成率（每10条笔记 ≈ 1% 完成率增长）
        suggestions = {k: v * 0.1 for k, v in category_counts.items()}
        return suggestions
    except (json.JSONDecodeError, KeyError):
        return {}


def build_subject_completion_update(inferred):
    """根据推断结果生成科目进度基线更新记录"""
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["科目进度基线"],
        "--as", "user",
        "--limit", "20",
        "--format", "json",
    ])
    
    if result.returncode != 0:
        return {}
    
    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        
        updates = {}
        for row in data_array:
            fields = dict(zip(field_names, row))
            subject = fields.get("科目", "")
            if subject in inferred:
                updates[subject] = inferred[subject]
        
        return updates
    except (json.JSONDecodeError, KeyError):
        return {}


def build_social_title(text):
    """从社交输入中提取标题（联系人 + 活动概要）"""
    # 去除前缀 #社交/#关系/#人脉
    for prefix in ["#社交", "#关系", "#人脉"]:
    for prefix in ["#社交", "#关系", "#人脉"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    # 去除亲密度标记
    t = re.sub(r'[★☆]+', '', text)
    # 去除生日标记
    t = re.sub(r'生日[：:]\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}', '', t)
    # 去除关系标签
    for tag in ["同学", "朋友", "家人", "同事", "学长", "学弟", "学姐", "合作伙伴"]:
        t = t.replace(tag, "")
    return re.sub(r'\s+', ' ', t).strip()


def _run_lark_cli(args_list, json_input=None):
    """运行lark-cli命令，兼容Windows环境
    
    Args:
        args_list: 命令参数列表（不含lark-cli本身）
        json_input: 可选的JSON字符串，写入临时文件后通过 @file 传给 --json
    """
    import subprocess
    import uuid

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


def deduplicate_check(table_name, title, target_date, dry_run=False):
    """去重检查：检查执行库中是否已有同日期的同名任务
    
    Args:
        table_name: 表名
        title: 任务标题
        target_date: 目标日期 (yyyy/MM/dd)
    
    Returns:
        True 表示存在重复，应该跳过；False 表示无重复，可以继续
    """
    if table_name != "执行库" or not target_date:
        return False
    
    if dry_run:
        return False
    
    # 读取执行库所有记录
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES[table_name],
        "--as", "user",
        "--limit", "200",
        "--format", "json",
    ])
    
    if result.returncode != 0:
        return False
    
    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        
        for row in data_array:
            fields = dict(zip(field_names, row))
            # 检查标题模糊匹配（±2字符误差容忍）
            if abs(len(fields.get("标题", "")) - len(title)) <= 2:
                if title in fields.get("标题", "") or fields.get("标题", "") in title:
                    # 检查截止日期匹配
                    dl = fields.get("截止日期", "")
                    if dl and str(dl)[:10].replace("-", "/") == str(target_date)[:10].replace("-", "/"):
                        print(f"⚠️ [去重] 检测到重复任务：'{title}'（截止日期 {target_date} 已在执行库中）")
                        return True
    except (json.JSONDecodeError, KeyError):
        pass
    
    return False


def insert_to_feishu(table_name, record_fields, target_date=None, dry_run=False):
    """通过 lark-cli 写入飞书多维表格（含去重逻辑）
    
    Args:
        table_name: 表名
        record_fields: 字段字典
        target_date: 目标日期，用于执行库去重检查
    """
    table_id = TABLES.get(table_name)
    if not table_id:
        return {"ok": False, "error": f"Unknown table: {table_name}"}

    # 过滤空值
    fields = {k: v for k, v in record_fields.items() if v is not None and v != ""}

    # 执行库去重检查
    if target_date and deduplicate_check(table_name, fields.get("标题", ""), target_date, dry_run):
        return {"ok": True, "deduplicated": True, "table": table_name, "title": fields.get("标题")}

    if dry_run:
        return {"ok": True, "dry_run": True, "table": table_name, "payload": fields}

    # record-upsert 直接传 Map<fieldName, CellValue>，不包装 fields
    json_str = json.dumps(fields, ensure_ascii=False)

    args = [
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", table_id,
        "--json", "@_record_json",
        "--as", "user",
    ]

    try:
        result = _run_lark_cli(args, json_input=json_str)
        output = result.stdout
        stderr = result.stderr

        if result.returncode == 0:
            return {"ok": True, "table": table_name, "output": output}
        else:
            return {"ok": False, "error": output or stderr, "returncode": result.returncode}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_energy_status(text):
    """处理 #精力 指令"""
    content = text.replace("#精力", "").strip()
    today = datetime.now().strftime("%Y/%m/%d")

    # 状态分类
    status_map = {
        "很差": "差",
        "不好": "差",
        "很差劲": "差",
        "一般": "一般",
        "还行": "一般",
        "好": "好",
        "很好": "好",
        "非常好": "好",
        "不错": "好",
    }

    energy_status = "一般"
    for keyword, status in status_map.items():
        if keyword in content:
            energy_status = status
            break

    # 写入临时记录到固定文件
    energy_file = os.path.join(os.path.dirname(__file__), "runtime", "_energy_status.json")
    try:
        with open(energy_file, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "status": energy_status, "raw": content}, f, ensure_ascii=False)
    except IOError:
        pass

    return {
        "ok": True,
        "type": "energy_status",
        "message": f"【{today}】精力状态：{energy_status}（原始反馈：{content}）",
        "suggestion": "精力系数已设为0.8，明日可用时长将缩减" if energy_status == "差" else ("精力系数已设为1.2，明日精力充沛" if energy_status == "好" else None),
    }


def handle_config(text):
    """处理 #配置 指令"""
    content = text.replace("#配置", "").strip()

    configs = {}

    # 解析各类配置项
    m = re.search(r'黄金段\s*(\d{1,2}[:：]\d{2})\s*[-—]\s*(\d{1,2}[:：]\d{2})', content)
    if m:
        configs["黄金段"] = f"{m.group(1)}-{m.group(2)}"

    m = re.search(r'常规段\s*(\d{1,2}[:：]\d{2})\s*[-—]\s*(\d{1,2}[:：]\d{2})', content)
    if m:
        configs["常规段"] = f"{m.group(1)}-{m.group(2)}"

    m = re.search(r'晚间段\s*(\d{1,2}[:：]\d{2})\s*[-—]\s*(\d{1,2}[:：]\d{2})', content)
    if m:
        configs["晚间段"] = f"{m.group(1)}-{m.group(2)}"

    m = re.search(r'可用时长\s*(\d+\.?\d*)\s*小时', content)
    if m:
        configs["今日可用时长"] = float(m.group(1))

    m = re.search(r'精力系数\s*(\d+\.?\d*)', content)
    if m:
        configs["精力系数"] = float(m.group(1))

    if "关闭" in content and "灵感提醒" in content:
        configs["灵感提醒"] = False
    if "开启" in content and "灵感提醒" in content:
        configs["灵感提醒"] = True

    # 写入配置到共享文件
    if configs:
        config_file = os.path.join(os.path.dirname(__file__), "runtime", "_schedule_config.json")
        try:
            existing = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing.update(configs)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except (IOError, json.JSONDecodeError):
            pass

    return {
        "ok": True,
        "type": "config",
        "configs": configs,
        "message": f"配置已更新：{json.dumps(configs, ensure_ascii=False)}",
    }


def handle_hatch(text, dry_run=False):
    """处理 #孵化 指令：从灵感库选取待孵化灵感转为执行库任务
    
    用法：
        #孵化                → 随机取第一条待孵化灵感转为任务
        #孵化 数学二          → 选取匹配的数学二灵感转为任务
    """
    # 可选：指定科目筛选
    project_filter = None
    content = text.replace("#孵化", "").strip()
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


def handle_review(days=7, dry_run=False):
    """处理 #复盘 指令：拉取过去N天的执行库记录，生成复盘报告
    
    Args:
        days: 回顾天数，默认7天
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # 读取执行库
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLES["执行库"],
        "--as", "user",
        "--limit", "500",
        "--format", "json",
    ])
    
    if result.returncode != 0:
        return {"ok": False, "error": "读取执行库失败"}
    
    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        
        total_tasks = 0
        completed = 0
        by_project = {}
        by_category = {}
        by_priority = {}
        time_spent = 0
        
        for row in data_array:
            fields = dict(zip(field_names, row))
            status = fields.get("状态", "")
            
            # 检查创建时间是否在回顾期内
            created = fields.get("创建时间", "")
            if created:
                try:
                    created_dt = datetime.strptime(str(created)[:19], "%Y-%m-%dT%H:%M:%S")
                    if not (start_date <= created_dt <= end_date):
                        continue
                except ValueError:
                    continue
            
            total_tasks += 1
            project = fields.get("所属项目", "未知")
            cat = fields.get("科目类别", "")
            priority = fields.get("轻重缓急", "P3")
            est_time = fields.get("预估耗时", 0) or 0
            
            try:
                est_time = int(est_time)
            except (ValueError, TypeError):
                est_time = 0
            
            if status == "已完成":
                completed += 1
                time_spent += est_time
            
            by_project[project] = by_project.get(project, 0) + 1
            if cat:
                by_category[cat] = by_category.get(cat, 0) + 1
            by_priority[priority] = by_priority.get(priority, 0) + 1
        
        completion_rate = round(completed / total_tasks * 100, 1) if total_tasks > 0 else 0
        
        # 生成复盘报告
        report = []
        report.append(f"📊 【{days}天复盘报告】（{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')}）")
        report.append(f"")
        report.append(f"总任务：{total_tasks} | 完成：{completed} | 完成率：{completion_rate}%")
        report.append(f"总耗时：{time_spent} 分钟（{time_spent/60:.1f}h）")
        report.append(f"")
        report.append("按项目分布：")
        for proj, cnt in sorted(by_project.items(), key=lambda x: -x[1]):
            report.append(f"  · {proj}：{cnt} 项")
        report.append(f"")
        if by_category:
            report.append("按科目分布：")
            for cat, cnt in sorted(by_category.items(), key=lambda x: -x[1]):
                report.append(f"  · {cat}：{cnt} 项")
            report.append(f"")
        report.append("按优先级分布：")
        for pri, cnt in sorted(by_priority.items(), key=lambda x: -x[1]):
            report.append(f"  · {pri}：{cnt} 项")
        
        return {
            "ok": True,
            "type": "review",
            "message": "\n".join(report),
            "stats": {
                "total": total_tasks,
                "completed": completed,
                "completion_rate": completion_rate,
                "time_spent": time_spent,
                "by_project": by_project,
                "by_category": by_category,
                "by_priority": by_priority,
            }
        }
    except (json.JSONDecodeError, KeyError):
        return {"ok": False, "error": "解析执行库数据失败"}


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


# ============ 主入口 ============

def main():
    if len(sys.argv) < 2:
        print("用法：python input_parser.py \"<消息文本>\" [--dry-run]")
        print("示例：python input_parser.py \"#任务 做数学真题 【项目：数学二】【精力：高】\"")
        sys.exit(1)

    # 处理参数
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    raw_text = " ".join(args)

    # 1. 检测前缀
    table_name, remaining = detect_prefix(raw_text)

    # 2. 特殊指令处理
    if table_name is None or raw_text.startswith("#精力"):
        if raw_text.startswith("#精力"):
            result = handle_energy_status(raw_text)
            print(format_output(result))
            sys.exit(0)
        elif raw_text.startswith("#配置"):
            result = handle_config(raw_text)
            print(format_output(result))
            sys.exit(0)
        elif raw_text.startswith("#孵化"):
            result = handle_hatch(raw_text, dry_run=dry_run)
            print(format_output(result))
            sys.exit(0)
        elif raw_text.startswith("#复盘"):
            # 可选：天数参数 #复盘 14
            days = 7
            m = re.search(r'#复盘\s+(\d+)', raw_text)
            if m:
                days = int(m.group(1))
            result = handle_review(days, dry_run=dry_run)
            print(format_output(result))
            sys.exit(0)
        else:
            all_prefixes = ["#任务", "#灵感", "#Bug", "#精力", "#配置", "#账单/#财务", "#社交/#关系/#人脉", "#创作/#作品", "#知识/#笔记/#学"]
            print(f"⚠️ 无法识别的指令。\n支持的前缀：{' '.join(all_prefixes)}")
            sys.exit(1)

    # 3. 提取变量
    vars = extract_variables(raw_text)

    # 4. 提取标题/主要内容
    title = extract_main_content(raw_text)
    if not title:
        print("⚠️ 未提取到主要内容标题")
        sys.exit(1)
    
    # 获取截止日期（用于去重）
    deadline = vars.get("截止日期")
    if not deadline:
        deadline = datetime.now().strftime("%Y/%m/%d")

    # 5. 构建记录
    record = build_record(table_name, title, vars, raw_text=raw_text)

    # 6. 写入飞书
    result = insert_to_feishu(table_name, record, target_date=deadline, dry_run=dry_run)
    
    # 处理去重情况
    if result.get("deduplicated"):
        print(f"[跳过] '{result.get('title')}' 今日已存在相同任务（去重）")
        sys.exit(0)
    
    print(format_output(result))

    # 详细输出
    if dry_run:
        print(f"\n解析详情：")
        print(f"  目标表：{table_name}")
        print(f"  标题：{title}")
        print(f"  变量：{json.dumps(vars, ensure_ascii=False)}")
        print(f"  记录：{json.dumps(record, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
