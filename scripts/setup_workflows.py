#!/usr/bin/env python3
"""
在飞书Base中创建云端自动化工作流。
用法: python setup_workflows.py [--dry-run]
"""
import subprocess
import json
import uuid
import os
import sys

BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
USER_OPEN_ID = "ou_adf2c637b6ddd79c0af429ad5da3a746"
LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\cli-connector-packages\lark-cli"

# 表名→真实表名
TABLE_NAMES = {
    "灵感库": "灵感库",
    "Bug库": "Bug库",
    "执行库": "执行库",
    "股市策略": "股市策略",
}

def run_lark(args_list, json_input=None):
    """运行lark-cli"""
    tmp_path = None
    if json_input:
        tmp_name = f"_wf_{uuid.uuid4().hex[:8]}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json_input)
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

    def try_decode(data):
        if data is None: return ""
        for enc in ["utf-8", "gbk", "gb2312", "cp936"]:
            try: return data.decode(enc)
            except: continue
        return data.decode("utf-8", errors="replace")

    cli_path = LARK_CLI.replace("\\", "/")
    cmd_parts = [f'"{cli_path}"'] + [f'"{a}"' for a in args_list]
    cmd_str = " ".join(cmd_parts)

    def _cleanup():
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass

    for bash_cmd in [r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe", "bash"]:
        try:
            result = subprocess.run([bash_cmd, "-c", cmd_str], capture_output=True, timeout=30)
            result.stdout = try_decode(result.stdout)
            result.stderr = try_decode(result.stderr)
            _cleanup()
            return result
        except (FileNotFoundError, OSError):
            continue

    _cleanup()
    raise FileNotFoundError("lark-cli not found")


def create_workflow(title, steps, dry_run=False):
    """创建工作流"""
    client_token = str(uuid.uuid4())
    body = {
        "client_token": client_token,
        "title": title,
        "steps": steps,
    }

    json_str = json.dumps(body, ensure_ascii=False)

    if dry_run:
        print(f"[DRY-RUN] 创建工作流: {title}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return {"ok": True, "dry_run": True}

    args = [
        "base", "+workflow-create",
        "--base-token", BASE_TOKEN,
        "--json", json_str,
        "--as", "user",
    ]
    result = run_lark(args, json_input=json_str)
    if result.returncode == 0:
        try:
            resp = json.loads(result.stdout)
            if resp.get("ok"):
                print(f"✅ 已创建: {title}")
                return resp
            else:
                print(f"❌ 创建失败 [{title}]: {resp}")
                return resp
        except json.JSONDecodeError:
            print(f"❌ 解析失败 [{title}]: {result.stdout}")
            return {"ok": False}
    else:
        print(f"❌ 命令失败 [{title}]: {result.stderr}")
        return {"ok": False, "error": result.stderr}


def enable_workflow(workflow_id, dry_run=False):
    """启用工作流"""
    if dry_run:
        print(f"[DRY-RUN] 启用工作流: {workflow_id}")
        return

    args = [
        "base", "+workflow-enable",
        "--base-token", BASE_TOKEN,
        "--workflow-id", workflow_id,
        "--as", "user",
    ]
    result = run_lark(args)
    if result.returncode == 0:
        print(f"✅ 已启用: {workflow_id}")
    else:
        print(f"❌ 启用失败: {result.stderr}")


# ============ 工作流定义 ============

def build_inspiration_notify():
    """新灵感通知：灵感库新增记录 → 发飞书消息"""
    return {
        "title": "新灵感通知",
        "steps": [
            {
                "id": "trigger_add",
                "type": "AddRecordTrigger",
                "title": "监控灵感库新增",
                "next": "send_msg",
                "data": {
                    "table_name": "灵感库",
                    "watched_field_name": "标题",
                }
            },
            {
                "id": "send_msg",
                "type": "LarkMessageAction",
                "title": "发送新灵感通知",
                "next": None,
                "data": {
                    "receiver": [
                        {"value_type": "user", "value": {"id": USER_OPEN_ID}}
                    ],
                    "send_to_everyone": False,
                    "title": [
                        {"value_type": "text", "value": "新灵感通知"}
                    ],
                    "content": [
                        {"value_type": "ref", "value": "$.trigger_add.recordLink"},
                        {"value_type": "text", "value": " 新增了一条灵感，请查看。"},
                    ],
                    "btn_list": []
                }
            }
        ]
    }


def build_bug_notify():
    """新Bug通知：Bug库新增记录 → 发飞书消息"""
    return {
        "title": "新Bug通知",
        "steps": [
            {
                "id": "trigger_add",
                "type": "AddRecordTrigger",
                "title": "监控Bug库新增",
                "next": "send_msg",
                "data": {
                    "table_name": "Bug库",
                    "watched_field_name": "标题",
                }
            },
            {
                "id": "send_msg",
                "type": "LarkMessageAction",
                "title": "发送新Bug通知",
                "next": None,
                "data": {
                    "receiver": [
                        {"value_type": "user", "value": {"id": USER_OPEN_ID}}
                    ],
                    "send_to_everyone": False,
                    "title": [
                        {"value_type": "text", "value": "新Bug通知"}
                    ],
                    "content": [
                        {"value_type": "ref", "value": "$.trigger_add.recordLink"},
                        {"value_type": "text", "value": " 新增了一条Bug，请查看。"},
                    ],
                    "btn_list": []
                }
            }
        ]
    }


def build_task_complete_notify():
    """任务完成通知：执行库状态改为已完成 → 发消息"""
    return {
        "title": "任务完成归档通知",
        "steps": [
            {
                "id": "trigger_update",
                "type": "SetRecordTrigger",
                "title": "监控状态变为已完成",
                "next": "send_msg",
                "data": {
                    "table_name": "执行库",
                    "field_watch_info": [
                        {"field_name": "状态", "operator": "is", "value": [{"value_type": "text", "value": "已完成"}]}
                    ],
                }
            },
            {
                "id": "send_msg",
                "type": "LarkMessageAction",
                "title": "发送完成通知",
                "next": None,
                "data": {
                    "receiver": [
                        {"value_type": "user", "value": {"id": USER_OPEN_ID}}
                    ],
                    "send_to_everyone": False,
                    "title": [
                        {"value_type": "text", "value": "任务已完成"}
                    ],
                    "content": [
                        {"value_type": "ref", "value": "$.trigger_update.recordLink"},
                        {"value_type": "text", "value": " 任务已完成，可去查看详情。"},
                    ],
                    "btn_list": []
                }
            }
        ]
    }


def build_inspiration_week_check():
    """灵感每周检查：每周日晚提醒灵感冷处理"""
    return {
        "title": "灵感周检查提醒",
        "steps": [
            {
                "id": "trigger_timer",
                "type": "TimerTrigger",
                "title": "每周日晚提醒",
                "next": "send_msg",
                "data": {
                    "rule": "WEEKLY",
                    "start_time": "2026-07-05 20:00",
                    "sub_unit": [0],
                    "is_never_end": True
                }
            },
            {
                "id": "send_msg",
                "type": "LarkMessageAction",
                "title": "发送检查提醒",
                "next": None,
                "data": {
                    "receiver": [
                        {"value_type": "user", "value": {"id": USER_OPEN_ID}}
                    ],
                    "send_to_everyone": False,
                    "title": [
                        {"value_type": "text", "value": "灵感周检查"}
                    ],
                    "content": [
                        {"value_type": "text", "value": "每周灵感清理时间。请去飞书灵感库浏览待处理的灵感，决定「转任务」或「放弃」。\n\n链接：https://my.feishu.cn/base/TtzIboiQQaPgfVszO2vc56wLnof"},
                    ],
                    "btn_list": []
                }
            }
        ]
    }


# ============ 主入口 ============

def main():
    dry_run = "--dry-run" in sys.argv

    workflows = [
        build_inspiration_notify(),
        build_bug_notify(),
        build_task_complete_notify(),
        build_inspiration_week_check(),
    ]

    results = []
    for wf in workflows:
        title = wf["title"]
        print(f"\n--- 创建: {title} ---")
        result = create_workflow(title, wf["steps"], dry_run)
        results.append(result)

        if not dry_run and result.get("ok"):
            wf_id = result.get("data", {}).get("workflow", {}).get("workflow_id", "")
            if wf_id:
                print(f"  工作流ID: {wf_id}")
                enable_workflow(wf_id)

    # 汇总
    success = sum(1 for r in results if r.get("ok"))
    print(f"\n{'='*40}")
    print(f"总计: {len(workflows)} 个，成功: {success} 个")


if __name__ == "__main__":
    main()
