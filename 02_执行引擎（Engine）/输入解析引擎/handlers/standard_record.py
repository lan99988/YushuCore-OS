"""
标准记录 handler（Step2-4-B）

迁移自 input_parser_old.py 的 main() 标准路径（第 2358–2391 行）。
严格遵守「搬家不装修」：仅搬运、不改行为、不改字段、不改输出格式。

覆盖范围（7 类前缀，由 detect_prefix 识别为对应 table_name）：
  #任务 #灵感 #Bug #账单/#财务 #社交/#关系/#人脉 #创作/#作品 #知识/#笔记/#学

数据流（与旧 main 一致，唯一驱动字段为 table_name）：
  extract_variables -> extract_main_content
  -> build_record -> insert_to_feishu(dry_run)
  -> [无标题 sys.exit(1)] / [去重 sys.exit(0)] -> 返回 result

说明：最终的 format_output 打印与 dry_run 详情块由 router.dispatch 统一负责，
      与特殊指令走同一条输出路径，本 handler 只产出 result。
"""

import sys
from datetime import datetime

from ..parser import extract_variables, extract_main_content
from ..builders import build_record
from ..feishu_write import insert_to_feishu


def handle_standard_record(table_name, raw_text, dry_run=False):
    """等价旧 main() 2358–2391 步骤 3–6 的标准记录逻辑。

    参数：
        table_name: detect_prefix 已解析出的目标表名（唯一驱动字段）
        raw_text:   原始用户输入
        dry_run:    为 True 时 insert_to_feishu 不真正写入飞书

    返回：insert_to_feishu 返回的 result dict（由调用方负责 format_output）。
    退出：无标题 -> sys.exit(1)；去重命中 -> sys.exit(0)（与旧 main 一致）。
    """
    vars = extract_variables(raw_text)

    title = extract_main_content(raw_text)
    if not title:
        print("⚠️ 未提取到主要内容标题")
        sys.exit(1)

    deadline = vars.get("截止日期")
    if not deadline:
        deadline = datetime.now().strftime("%Y/%m/%d")

    record = build_record(table_name, title, vars, raw_text=raw_text)

    result = insert_to_feishu(table_name, record, target_date=deadline, dry_run=dry_run)

    if result.get("deduplicated"):
        print(f"[跳过] '{result.get('title')}' 今日已存在相同任务（去重）")
        sys.exit(0)

    return result
