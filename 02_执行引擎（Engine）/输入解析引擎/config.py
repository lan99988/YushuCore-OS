"""
输入解析引擎配置中心

集中管理飞书 Base 常量与指令映射。
本文件仅存放常量，不含任何业务逻辑。

迁移来源：input_parser.py 顶部「配置」段（行 56-142），
值保持 100% 一致，仅补充必需的 import（os / shutil）。
"""

import os
import shutil

# ============ 配置 ============
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"

# lark-cli 路径（Windows下需要通过bash执行shell包装器）
LARK_CLI_SCRIPT = r"C:\Users\26326\.workbuddy\binaries\node\cli-connector-packages\lark-cli"

# 检测是否可以通过直接调用运行
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
    "习惯追踪表": "tblSRdG4P3XE75Ll",  # 🆕 习惯追踪
    "比赛管理表": "tblKPdoxMHy7FuV7",   # 🆕 比赛管理
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
    "#习惯": None,  # 🆕 习惯：创建/查看/管理习惯
    "#习惯打卡": None,  # 🆕 习惯打卡
    "#习惯进度": None,  # 🆕 习惯进度
    "#深度规划": None,  # 🆕 深度工作规划
    "#深度记录": None,  # 🆕 深度工作记录
    "#深度": None,  # 🆕 深度工作通用入口（自动判断）
    "#注意力审计": None,  # 🆕 注意力经济审计
    "#排程到日历": None,  # 特殊处理：同步排程到飞书日历
    "#日历": None,  # #日历 是 #排程到日历 的简写
    "#比赛": None,  # 🆕 比赛管理
    "#身体": None,  # 🆕 Body OS 唯一入口
    "#训练": None,  # 🆕 Body OS 训练记录/建议
    "#营养": None,  # 🆕 Body OS 营养记录/建议
    "#恢复": None,  # 🆕 Body OS 恢复判断
    "#体测": None,  # 🆕 Body OS 指标/趋势
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
