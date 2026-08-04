"""
参数提取层

迁移自 input_parser_old.py（原样搬运，逻辑 0 改动）：
parse_bill_vars            解析 #账单/#财务 财务变量
parse_social_vars          解析 #社交/#关系/#人脉 社交变量
parse_create_vars          解析 #创作/#作品 创作变量
parse_knowledge_vars       解析 #知识/#笔记/#学 知识变量
build_social_title         从社交输入提取标题（联系人+活动概要，纯函数）
build_subject_completion_update 根据推断结果生成科目进度基线更新记录

依赖说明：
- 前 5 个函数为纯函数（仅用 re / 局部字面量），无外部状态。
- build_subject_completion_update 依赖 _run_lark_cli（网络）与 config 常量，
  原样保留其调用方式，仅把全局引用改为显式导入。

重要事实（迁移时确认）：
旧文件中 build_social_title 被定义了两次（632 行与 711 行）。
632 行版本实为「查询知识笔记表推断完成率」的误命名函数，且被 711 行版本
在模块命名空间中原样覆盖（Python 后定义覆盖先定义），运行时 build_social_title
恒等于 711 行纯函数版本；632 行版本为不可达死代码。本模块仅迁移 ACTIVE 的
711 行版本，以精确保留现有行为。
"""

import json
import re
from datetime import datetime

from .config import BASE_TOKEN, TABLES
from .lark_bridge import _run_lark_cli


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
    """从社交输入中提取标题（联系人 + 活动概要）"""
    # 去除前缀 #社交/#关系/#人脉
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
