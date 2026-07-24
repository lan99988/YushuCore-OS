#!/usr/bin/env python3
"""
比赛管理模块 - Competition Manager
===================================
处理 #比赛 前缀的所有子命令。
数据表：比赛管理表（飞书Base）
依托个人混合管理系统，通过 input_parser.py 路由调用。

用法：
    #比赛 创建 比赛名称 【日期：2026/09/15】【地点：深圳】【人员：我自己,张三】【链接：https://xxx.com】
    #比赛 [名称] 报名 【截止：2026/09/10】【费用：100】
    #比赛 [名称] 初赛 【日期：2026/09/20】【结果：晋级】
    #比赛 [名称] 初赛 跳过
    #比赛 [名称] 决赛 【日期：2026/10/01】【结果：获奖】
    #比赛 [名称] 决赛 不适用
    #比赛 [名称] 成绩 【成绩：二等奖】【奖状：证书编号】
    #比赛 [名称] 奖金 【金额：2000】【状态：已完成】
    #比赛 [名称] 报销 【金额：500】【状态：已完成】
    #比赛 [名称] 上传凭证 <图片路径>  → 报名费凭证
    #比赛 [名称] 上传报销 <图片路径>  → 报名费凭证（报销用）
    #比赛 [名称] 上传奖状 <图片路径>  → 奖状图片
    #比赛 列表
    #比赛 [名称]
    #比赛 帮助
"""

import re
import json
import os
import sys
from datetime import datetime

# ============ 配置（由 set_config 注入） ============
_BASE_TOKEN = None
_TABLES = None       # input_parser 的 TABLES dict
_run_lark_cli = None # input_parser 的 _run_lark_cli 函数
_COMP_TABLE_ID = None

# 表名（用于从 TABLES 查找 ID）
TABLE_NAME = "比赛管理表"

# ============ 阶段配置 ============

STAGE_CONFIG = [
    {"key": "报名",      "label": "报名",      "icons": "📝"},
    {"key": "参加初赛",  "label": "初赛",      "icons": "🏃"},
    {"key": "参加决赛",  "label": "决赛",      "icons": "🏆"},
    {"key": "成绩与奖状","label": "成绩",      "icons": "📊"},
    {"key": "申请奖金",  "label": "奖金",      "icons": "💰"},
    {"key": "奖金报销",  "label": "报销",      "icons": "🧾"},
]


def set_config(base_token, tables, run_lark_cli_func):
    """由 input_parser.py 调用，注入全局配置"""
    global _BASE_TOKEN, _TABLES, _run_lark_cli, _COMP_TABLE_ID
    _BASE_TOKEN = base_token
    _TABLES = tables
    _run_lark_cli = run_lark_cli_func
    _COMP_TABLE_ID = tables.get(TABLE_NAME)


# ============ 辅助函数 ============

def _get(fields, field_name, default=None):
    """安全获取字段值（兼容列表类型）"""
    v = fields.get(field_name, default)
    if isinstance(v, list) and v:
        return v[0]
    return v if v is not None else default


def _progress_bar(ratio, width=16):
    """生成 ASCII 进度条"""
    ratio = max(0, min(1, ratio))
    filled = int(width * ratio)
    return "█" * filled + "░" * (width - filled)


def _fetch_all_records():
    """读取比赛管理表全部记录
    
    Returns:
        (field_names, data_array, record_id_list) 元组, 或 None
    """
    if not _COMP_TABLE_ID:
        return None, "比赛管理表未注册，请在 input_parser.py 的 TABLES 中配置"
    
    result = _run_lark_cli([
        "base", "+record-list",
        "--base-token", _BASE_TOKEN,
        "--table-id", _COMP_TABLE_ID,
        "--as", "user",
        "--limit", "200",
        "--format", "json",
    ])
    if result.returncode != 0:
        return None, f"读取比赛表失败：{result.stderr or result.stdout}"
    
    try:
        resp = json.loads(result.stdout)
        d = resp.get("data", {})
        field_names = d.get("fields", [])
        data_array = d.get("data", [])
        record_ids = d.get("record_id_list", [])
        return (field_names, data_array, record_ids), None
    except (json.JSONDecodeError, KeyError) as e:
        return None, f"解析比赛表数据失败：{e}"


def _find_competition(records, name):
    """按名称模糊匹配查找比赛"""
    field_names, data_array, record_ids = records
    best_match = None
    best_score = 0
    
    for idx, row in enumerate(data_array):
        fields = dict(zip(field_names, row))
        comp_name = str(_get(fields, "比赛名称", "") or "")
        
        # 精确匹配优先
        if comp_name == name:
            fields["_record_id"] = record_ids[idx] if idx < len(record_ids) else ""
            return fields, None
        
        # 模糊匹配
        if name in comp_name:
            score = len(name) / max(len(comp_name), 1)
            if score > best_score:
                best_score = score
                fields["_record_id"] = record_ids[idx] if idx < len(record_ids) else ""
                best_match = fields
    
    if best_match:
        return best_match, None
    return None, f"未找到比赛「{name}」"


def _extract_kv(text):
    """从文本中提取所有【key:value】到字典"""
    vars = {}
    for m in re.finditer(r'【([^：:]+)[：:]\s*(.+?)】', text):
        key = m.group(1).strip()
        value = m.group(2).strip()
        vars[key] = value
    return vars


def _update_record(rec_id, update_fields):
    """更新飞书记录"""
    if not rec_id:
        return {"ok": False, "error": "无记录 ID"}
    
    fields = {k: v for k, v in update_fields.items() if v is not None and v != ""}
    if not fields:
        return {"ok": False, "error": "没有要更新的字段"}
    
    result = _run_lark_cli([
        "base", "+record-batch-update",
        "--base-token", _BASE_TOKEN,
        "--table-id", _COMP_TABLE_ID,
        "--json", "@_record_json",
        "--as", "user",
    ], json_input=json.dumps({
        "record_id_list": [rec_id],
        "patch": fields
    }, ensure_ascii=False))
    
    if result.returncode == 0:
        return {"ok": True, "updated": fields}
    return {"ok": False, "error": f"更新失败：{result.stderr or result.stdout}"}


def _calc_stage_statuses(fields):
    """计算6个阶段的完成状态，返回 [(key, label, done, detail), ...]"""
    results = []
    
    # 1. 报名：有截止日期或费用 → 已完成
    has_reg = bool(_get(fields, "报名截止") or _get(fields, "报名费用"))
    results.append(("报名", "报名", has_reg, "已填写" if has_reg else "未填写"))
    
    # 2. 初赛
    ps = _get(fields, "初赛状态", "未开始")
    done_ps = ps in ("已完成", "跳过仅一轮")
    results.append(("参加初赛", "初赛", done_ps, ps))
    
    # 3. 决赛
    fs = _get(fields, "决赛状态", "未开始")
    done_fs = fs in ("已完成", "不适用")
    results.append(("参加决赛", "决赛", done_fs, fs))
    
    # 4. 成绩与奖状
    has_score = bool(_get(fields, "最终成绩"))
    results.append(("成绩与奖状", "成绩", has_score, 
                    _get(fields, "最终成绩", "未填写") if has_score else "未填写"))
    
    # 5. 奖金
    ba = _get(fields, "奖金申请状态", "未开始")
    done_ba = ba == "已完成"
    results.append(("申请奖金", "奖金", done_ba, ba))
    
    # 6. 报销
    rb = _get(fields, "报销状态", "未开始")
    done_rb = rb == "已完成"
    results.append(("奖金报销", "报销", done_rb, rb))
    
    return results


# ============ 命令处理函数 ============

def handle_create(text, dry_run=False):
    """处理 #比赛 创建 ..."""
    content = text
    for p in ["#比赛 创建", "#比赛创建"]:
        if content.startswith(p):
            content = content[len(p):].strip()
    
    vars = _extract_kv(content)
    
    # 去除【】后剩余文本作为名称
    name = re.sub(r'【[^】]*?】', '', content).strip()
    if not name:
        return {"ok": False, "error": "请指定比赛名称，如：`#比赛 创建 王者荣耀高校赛 【日期：2026/09/15】`"}
    
    # 解析日期（支持 2026/09/15、9月15日 等）
    date_str = vars.get("日期", datetime.now().strftime("%Y/%m/%d"))
    
    # 解析报名费用
    fee = None
    if vars.get("费用"):
        try:
            fee = int(float(vars["费用"]))
        except ValueError:
            pass
    
    fields = {
        "比赛名称": name,
        "日期": date_str,
        "地点": vars.get("地点", ""),
        "参赛人员": vars.get("人员", "我自己"),
        "比赛链接": vars.get("链接", ""),
        "报名截止": vars.get("截止", ""),
        "报名费用": fee,
        "报名备注": vars.get("备注", ""),
        "初赛状态": "未开始",
        "决赛状态": "未开始",
        "奖金申请状态": "未开始",
        "报销状态": "未开始",
        "初赛结果": "待定",
        "决赛结果": "待定",
    }
    fields = {k: v for k, v in fields.items() if v is not None and v != ""}
    
    if dry_run:
        return {"ok": True, "dry_run": True, "type": "competition",
                "message": f"[TEST] 创建比赛「{name}」\n{json.dumps(fields, ensure_ascii=False, indent=2)}"}
    
    json_str = json.dumps(fields, ensure_ascii=False)
    result = _run_lark_cli([
        "base", "+record-upsert",
        "--base-token", _BASE_TOKEN,
        "--table-id", _COMP_TABLE_ID,
        "--json", "@_record_json",
        "--as", "user",
    ], json_input=json_str)
    
    if result.returncode == 0:
        msg_parts = [f"✅ 比赛「{name}」已创建"]
        if vars.get("日期"): msg_parts.append(f"  📅 日期：{vars['日期']}")
        if vars.get("地点"): msg_parts.append(f"  📍 地点：{vars['地点']}")
        if vars.get("人员"): msg_parts.append(f"  👥 人员：{vars['人员']}")
        if vars.get("链接"): msg_parts.append(f"  🔗 链接：{vars['链接']}")
        return {"ok": True, "type": "competition", "message": "\n".join(msg_parts)}
    return {"ok": False, "error": f"写入失败：{result.stderr or result.stdout}"}


def handle_update(text, dry_run=False):
    """处理 #比赛 [名称] [阶段] 【key:value】"""
    content = text.replace("#比赛", "").strip()
    
    # 动作词列表
    actions = ["报名", "初赛", "决赛", "成绩", "奖金", "报销", "列表", "帮助", "创建"]
    
    # 分离比赛名称和阶段动作
    name = ""
    stage = ""
    rest = ""
    
    tokens = content.split()
    for i, token in enumerate(tokens):
        if token in actions and i > 0:
            name = " ".join(tokens[:i])
            stage = token
            rest = " ".join(tokens[i+1:])
            break
    
    if not name:
        name = content  # 没有匹配到阶段词，整个作为名称（用于查询详情）
    
    vars = _extract_kv(content)
    
    # 读取数据库
    records, err = _fetch_all_records()
    if err:
        return {"ok": False, "error": err}
    if records is None:
        return {"ok": True, "type": "competition", "message": "📋 比赛管理表中暂无数据"}
    
    competition, err = _find_competition(records, name)
    if err:
        return {"ok": False, "error": err}
    
    rec_id = competition.get("_record_id", "")
    comp_name = _get(competition, "比赛名称", name)
    
    # 构建更新字段
    update_fields = {}
    
    if stage == "报名":
        if vars.get("截止"): update_fields["报名截止"] = vars["截止"]
        if vars.get("费用"):
            try: update_fields["报名费用"] = int(float(vars["费用"]))
            except ValueError: pass
        if vars.get("备注"): update_fields["报名备注"] = vars["备注"]
        if vars.get("人员"): update_fields["参赛人员"] = vars["人员"]
    
    elif stage == "初赛":
        # 跳过初赛
        for skip_word in ["跳过", "skip", "Skip", "SKIP"]:
            if skip_word in rest:
                update_fields["初赛状态"] = "跳过仅一轮"
                update_fields["初赛结果"] = "不适用"
                break
        else:
            # 正常更新
            if vars.get("状态"):
                s = vars["状态"]
                if s in ("未开始", "进行中", "已完成", "跳过仅一轮"):
                    update_fields["初赛状态"] = s
                else:
                    return {"ok": False, "error": f"初赛状态只能为：未开始/进行中/已完成/跳过仅一轮"}
            else:
                update_fields["初赛状态"] = "已完成"
            if vars.get("日期"): update_fields["初赛日期"] = vars["日期"]
            if vars.get("结果"):
                if vars["结果"] in ("晋级", "未晋级"):
                    update_fields["初赛结果"] = vars["结果"]
                else:
                    return {"ok": False, "error": f"初赛结果只能为：晋级/未晋级"}
            if vars.get("备注"): update_fields["初赛备注"] = vars["备注"]
    
    elif stage == "决赛":
        # 无决赛
        for skip_word in ["不适用", "无", "na", "NA", "N/A", "n/a"]:
            if skip_word in rest:
                update_fields["决赛状态"] = "不适用"
                update_fields["决赛结果"] = "不适用"
                break
        else:
            if vars.get("状态"):
                s = vars["状态"]
                if s in ("未开始", "进行中", "已完成", "不适用"):
                    update_fields["决赛状态"] = s
                else:
                    return {"ok": False, "error": f"决赛状态只能为：未开始/进行中/已完成/不适用"}
            else:
                update_fields["决赛状态"] = "已完成"
            if vars.get("日期"): update_fields["决赛日期"] = vars["日期"]
            if vars.get("结果"):
                if vars["结果"] in ("获奖", "未获奖"):
                    update_fields["决赛结果"] = vars["结果"]
                else:
                    return {"ok": False, "error": f"决赛结果只能为：获奖/未获奖"}
            if vars.get("备注"): update_fields["决赛备注"] = vars["备注"]
    
    elif stage == "成绩":
        if vars.get("成绩"): update_fields["最终成绩"] = vars["成绩"]
        if vars.get("奖状"): update_fields["奖状信息"] = vars["奖状"]
    
    elif stage == "奖金":
        if vars.get("状态"):
            s = vars["状态"]
            if s in ("未开始", "进行中", "已完成"):
                update_fields["奖金申请状态"] = s
            else:
                return {"ok": False, "error": f"奖金申请状态只能为：未开始/进行中/已完成"}
        else:
            update_fields["奖金申请状态"] = "已完成"
        if vars.get("金额"):
            try: update_fields["奖金金额"] = int(float(vars["金额"]))
            except ValueError: pass
        if vars.get("日期"): update_fields["奖金申请日期"] = vars["日期"]
    
    elif stage == "报销":
        if vars.get("状态"):
            s = vars["状态"]
            if s in ("未开始", "进行中", "已完成"):
                update_fields["报销状态"] = s
            else:
                return {"ok": False, "error": f"报销状态只能为：未开始/进行中/已完成"}
        else:
            update_fields["报销状态"] = "已完成"
        if vars.get("金额"):
            try: update_fields["报销金额"] = int(float(vars["金额"]))
            except ValueError: pass
        if vars.get("日期"): update_fields["报销日期"] = vars["日期"]
        if vars.get("备注"): update_fields["报销备注"] = vars["备注"]
    
    else:
        # 没有匹配的阶段 → 显示详情
        return handle_detail(competition, records)
    
    if not update_fields:
        return {"ok": False, "error": f"没有检测到要更新的字段，请使用【key:value】格式"}
    
    if dry_run:
        return {"ok": True, "dry_run": True, "type": "competition",
                "message": f"[TEST] 更新比赛「{comp_name}」阶段={stage}\n{json.dumps(update_fields, ensure_ascii=False, indent=2)}"}
    
    update_result = _update_record(rec_id, update_fields)
    if update_result.get("ok"):
        stage_icons = {"报名": "📝", "初赛": "🏃", "决赛": "🏆",
                       "成绩": "📊", "奖金": "💰", "报销": "🧾"}
        icon = stage_icons.get(stage, "📌")
        msg = [f"{icon} 【{comp_name}】- {stage}阶段已更新"]
        for k, v in update_fields.items():
            msg.append(f"  · {k}：{v}")
        return {"ok": True, "type": "competition", "message": "\n".join(msg)}
    return {"ok": False, "error": update_result.get("error")}


def handle_list(dry_run=False):
    """处理 #比赛 列表：显示所有比赛概览"""
    records, err = _fetch_all_records()
    if err:
        return {"ok": False, "error": err}
    if records is None:
        return {"ok": True, "type": "competition", "message": "📋 比赛管理表中暂无数据"}
    
    field_names, data_array, record_ids = records
    if not data_array:
        return {"ok": True, "type": "competition", "message": "📋 比赛管理表中暂无数据"}
    
    report_lines = ["📊 【比赛总览】"]
    report_lines.append("━" * 30)
    
    for row in data_array:
        fields = dict(zip(field_names, row))
        
        name = _get(fields, "比赛名称", "未命名") or "未命名"
        location = _get(fields, "地点", "") or ""
        participants = _get(fields, "参赛人员", "") or ""
        
        # 计算进度
        stage_statuses = _calc_stage_statuses(fields)
        completed = sum(1 for s in stage_statuses if s[2])
        total = len(stage_statuses)
        pct = int(completed / total * 100)
        
        # 标题行
        loc_tag = f" ({location})" if location else ""
        report_lines.append(f"  🏆 {name}{loc_tag}")
        if participants:
            report_lines.append(f"     👥 {participants}")
        link = _get(fields, "比赛链接", "") or ""
        if link:
            report_lines.append(f"     🔗 {link}")
        
        # 每阶段进度
        for key, label, done, detail in stage_statuses:
            icon_map = {"报名": "📝", "参加初赛": "🏃", "参加决赛": "🏆",
                        "成绩与奖状": "📊", "申请奖金": "💰", "奖金报销": "🧾"}
            icon = icon_map.get(key, "  ")
            bar = _progress_bar(1 if done else 0, 8)
            status_text = f"✅ 已完成" if done else f"⏳ {detail}"
            report_lines.append(f"    {icon} {label}\t{bar} {status_text}")
        
        # 总进度
        report_lines.append(f"  {'─' * 25}")
        bar = _progress_bar(pct / 100, 20)
        report_lines.append(f"  进度: {bar} {pct}%")
        report_lines.append("")
    
    return {"ok": True, "type": "competition", "message": "\n".join(report_lines)}


def handle_upload_attachment(text, dry_run=False):
    """处理 #比赛 [名称] 上传凭证/奖状 <文件路径>"""
    content = text.replace("#比赛", "").strip()
    tokens = content.split()
    
    # 查找动作词位置
    action = None
    action_idx = -1
    for i, token in enumerate(tokens):
        if token in ("上传凭证", "上传奖状", "上传报销"):
            action = token
            action_idx = i
            break
    
    if action_idx <= 0:
        return {"ok": False, "error": "请指定比赛名称，如：`#比赛 [名称] 上传凭证 <文件路径>`"}
    
    name = " ".join(tokens[:action_idx])
    file_path = " ".join(tokens[action_idx + 1:]).strip()
    
    if not file_path:
        return {"ok": False, "error": "请提供文件路径，如：`#比赛 [名称] 上传凭证 C:\\Users\\xxx\\payment.jpg`"}
    
    # 规范化路径：Windows 路径保持 Windows 格式用于 os.path.exists/shutil
    # 但支持用户输入 D:\xxx 或 /d/xxx
    if file_path.startswith("/d/"):
        win_path = "D:\\" + file_path[3:].replace("/", "\\")
    elif file_path.startswith("/c/"):
        win_path = "C:\\" + file_path[3:].replace("/", "\\")
    else:
        win_path = file_path.replace("\\", "/")
        if win_path.startswith("D:/"):
            win_path = "D:\\" + win_path[3:].replace("/", "\\")
        elif win_path.startswith("C:/"):
            win_path = "C:\\" + win_path[3:].replace("/", "\\")
        elif win_path.startswith("d:/"):
            win_path = "D:\\" + win_path[3:].replace("/", "\\")
        elif win_path.startswith("c:/"):
            win_path = "C:\\" + win_path[3:].replace("/", "\\")
    
    file_path = win_path
    
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"文件不存在：{file_path}"}
    
    # 查找比赛记录
    records, err = _fetch_all_records()
    if err:
        return {"ok": False, "error": err}
    competition, err = _find_competition(records, name)
    if err:
        return {"ok": False, "error": err}
    
    rec_id = competition.get("_record_id", "")
    comp_name = _get(competition, "比赛名称", name)
    
    # 确定字段
    if action in ("上传凭证", "上传报销"):
        field_name = "报名费凭证"
    else:
        field_name = "奖状图片"
    
    # 获取 field id
    result = _run_lark_cli([
        "base", "+field-list",
        "--base-token", _BASE_TOKEN,
        "--table-id", _COMP_TABLE_ID,
        "--as", "user",
        "--format", "json",
    ])
    if result.returncode != 0:
        return {"ok": False, "error": f"读取字段列表失败：{result.stderr or result.stdout}"}
    
    try:
        resp = json.loads(result.stdout)
        field_id = None
        for f in resp["data"]["fields"]:
            if f["name"] == field_name:
                field_id = f["id"]
                break
        if not field_id:
            return {"ok": False, "error": f"未找到字段：{field_name}，请先用 lark-cli +field-create 创建"}
    except Exception as e:
        return {"ok": False, "error": f"解析字段列表失败：{e}"}
    
    if dry_run:
        return {"ok": True, "dry_run": True, "type": "competition",
                "message": f"[TEST] 上传{field_name}到「{comp_name}」\n  文件：{file_path}\n  字段ID：{field_id}"}
    
    # lark-cli 要求相对路径，复制到当前目录
    cwd = os.getcwd()
    basename = os.path.basename(file_path)
    local_copy = os.path.join(cwd, f"_comp_upload_{basename}")
    try:
        import shutil
        shutil.copy2(file_path, local_copy)
    except Exception as e:
        return {"ok": False, "error": f"复制文件失败：{e}"}
    
    try:
        result = _run_lark_cli([
            "base", "+record-upload-attachment",
            "--base-token", _BASE_TOKEN,
            "--table-id", _COMP_TABLE_ID,
            "--record-id", rec_id,
            "--field-id", field_id,
            "--file", f"./_comp_upload_{basename}",
            "--as", "user",
        ])
    finally:
        try:
            os.remove(local_copy)
        except Exception:
            pass
    
    if result.returncode == 0:
        return {"ok": True, "type": "competition",
                "message": f"✅ 已上传「{field_name}」到比赛「{comp_name}」\n  文件：{basename}"}
    return {"ok": False, "error": f"上传失败：{result.stderr or result.stdout}"}


def handle_detail(competition, records=None):
    """显示单个比赛详情"""
    if competition is None and records is not None:
        records, err = _fetch_all_records()
        if err:
            return {"ok": False, "error": err}
        if records is None:
            return {"ok": True, "type": "competition_detail",
                    "message": "比赛管理表中暂无数据"}
    
    name = _get(competition, "比赛名称", "")
    
    lines = [f"🏆 【比赛详情：{name}】"]
    lines.append("━" * 30)
    
    # 基本信息
    lines.append(f"  📅 日期：{_get(competition, '日期', '未设置')}")
    lines.append(f"  📍 地点：{_get(competition, '地点', '未设置')}")
    lines.append(f"  👥 人员：{_get(competition, '参赛人员', '未设置')}")
    link = _get(competition, '比赛链接', '')
    if link:
        lines.append(f"  🔗 链接：{link}")
    lines.append("")
    
    # 阶段详情
    sections = [
        ("📝 报名", [
            ("截止", "报名截止"), ("费用", "报名费用", "元"), ("备注", "报名备注"),
        ]),
        ("🏃 初赛", [
            ("状态", "初赛状态"), ("日期", "初赛日期"),
            ("结果", "初赛结果"), ("备注", "初赛备注"),
        ]),
        ("🏆 决赛", [
            ("状态", "决赛状态"), ("日期", "决赛日期"),
            ("结果", "决赛结果"), ("备注", "决赛备注"),
        ]),
        ("📊 成绩与奖状", [
            ("成绩", "最终成绩"), ("奖状", "奖状信息"),
        ]),
        ("💰 申请奖金", [
            ("状态", "奖金申请状态"), ("金额", "奖金金额", "元"),
            ("日期", "奖金申请日期"),
        ]),
        ("🧾 报销", [
            ("状态", "报销状态"), ("金额", "报销金额", "元"),
            ("日期", "报销日期"), ("备注", "报销备注"),
        ]),
    ]
    
    for section_title, field_list in sections:
        lines.append(f"  {section_title}")
        has_content = False
        for item in field_list:
            label = item[0]
            field_name = item[1]
            suffix = item[2] if len(item) > 2 else ""
            val = _get(competition, field_name, "")
            
            # 适配 checkbox 类型
            if isinstance(val, bool):
                display = "✅ 是" if val else "⬜ 否"
                has_content = True
                lines.append(f"    · {label}：{display}")
            elif val or field_name.endswith("状态"):
                display = val if val else "未设置"
                has_content = True
                lines.append(f"    · {label}：{display}{suffix}")
        
        if not has_content:
            lines.append("    （暂无数据）")
        lines.append("")
    
    return {"ok": True, "type": "competition_detail", "message": "\n".join(lines)}


def handle_help():
    """显示帮助信息"""
    help_text = (
        "📋 【比赛管理模块使用帮助】\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 创建比赛：\n"
        "  #比赛 创建 比赛名称 【日期：2026/09/15】【地点：深圳】【人员：我自己,张三】【链接：https://xxx.com】\n\n"
        "📌 更新各阶段：\n"
        "  #比赛 [名称] 报名   【截止：2026/09/10】【费用：100】\n"
        "  #比赛 [名称] 初赛   【日期：2026/09/20】【结果：晋级】\n"
        "  #比赛 [名称] 初赛 跳过    （仅一轮比赛时用）\n"
        "  #比赛 [名称] 决赛   【日期：2026/10/01】【结果：获奖】\n"
        "  #比赛 [名称] 决赛 不适用   （无决赛时用）\n"
        "  #比赛 [名称] 成绩   【成绩：二等奖】【奖状：已上传】\n"
        "  #比赛 [名称] 奖金   【金额：2000】【状态：已完成】\n"
        "  #比赛 [名称] 报销   【金额：500】【状态：已完成】\n\n"
        "📎 上传图片附件：\n"
        "  #比赛 [名称] 上传凭证 <图片路径>    → 上传到「报名费凭证」(报名费、报销凭证)\n"
        "  #比赛 [名称] 上传报销 <图片路径>    → 同上，上传到「报名费凭证」\n"
        "  #比赛 [名称] 上传奖状 <图片路径>    → 上传到「奖状图片」(证书/奖状)\n\n"
        "📊 查看：\n"
        "  #比赛 列表              → 全部比赛概览（含进度条）\n"
        "  #比赛 [名称]            → 单场比赛详情\n\n"
        "💡 提示：\n"
        "  · 初赛结果：晋级 / 未晋级\n"
        "  · 决赛结果：获奖 / 未获奖\n"
        "  · 各阶段状态：未开始 / 进行中 / 已完成\n"
        "  · 初赛可「跳过」（仅一轮比赛）\n"
        "  · 决赛可设为「不适用」（无决赛）\n"
        "  · 参赛人员用逗号分隔：我自己,张三,李四\n"
        "  · 所有命令支持 --dry-run 测试模式"
    )
    return {"ok": True, "type": "competition", "message": help_text}


# ============ 统一入口 ============

def main_handler(text, dry_run=False):
    """统一入口：由 input_parser.py 调用
    
    Args:
        text: 包含 #比赛 前缀的完整输入文本
        dry_run: 是否测试模式（不实际写入）
    
    Returns:
        dict: {"ok": bool, "type": str, "message": str, ...}
    """
    content = text.replace("#比赛", "").strip()
    
    if not content or content in ("帮助", "help", "?"):
        return handle_help()
    
    # 检测子命令
    if content.startswith("创建") or content.startswith("create"):
        return handle_create(text, dry_run)
    elif content in ("列表", "list", "总览"):
        return handle_list(dry_run)
    elif any(upload_word in content.split() for upload_word in ["上传凭证", "上传报销", "上传奖状"]):
        return handle_upload_attachment(text, dry_run)
    else:
        # 尝试更新或查询
        return handle_update(text, dry_run)


# ============ 直接运行测试 ============

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python competition_manager.py \"#比赛 列表\" [--dry-run]")
        sys.exit(1)
    
    test_text = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    
    # 注入测试用配置
    from input_parser import BASE_TOKEN, TABLES, _run_lark_cli as run_func
    set_config(BASE_TOKEN, TABLES, run_func)
    
    result = main_handler(test_text, dry_run)
    if result.get("ok"):
        if "type" in result and result["type"] in ("competition", "competition_detail"):
            print(result["message"])
        elif result.get("dry_run"):
            print(result["message"])
        else:
            print(f"[OK] {result.get('message', '成功')}")
    else:
        print(f"[失败] {result.get('error', '未知错误')}")
