#!/usr/bin/env python3
"""
飞书Base深度工作仪表盘组件创建脚本
==================================
串行创建8个可视化组件到「深度工作仪表盘」。

用法：
    python "05_自动化工作流（Automation）/脚本/create_dashboard.py"
"""

import json
import subprocess
import os
import sys
import time

LARK_CLI = r"C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\.bin\lark-cli.cmd"
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"
DASHBOARD_ID = "blkWvXoRlXnKKZxL"
TABLE_NAME = "深度工作追踪表"

# 8个组件定义
COMPONENTS = [
    {
        "name": "仪表盘标题",
        "type": "text",
        "data_config": {
            "text": "# 📊 深度工作仪表盘\n追踪核心指标，数据随 `#深度记录` 指令自动更新\n\n## 🎯 4DX引领指标 vs 滞后指标"
        }
    },
    {
        "name": "4DX周累计深度(h)",
        "type": "statistics",
        "data_config": {
            "table_name": TABLE_NAME,
            "series": [{"field_name": "计分板周累计深度(h)", "rollup": "MAX"}]
        }
    },
    {
        "name": "每日深度时长趋势",
        "type": "line",
        "data_config": {
            "table_name": TABLE_NAME,
            "series": [{"field_name": "当日深度工作时长(min)", "rollup": "SUM"}],
            "group_by": [{"field_name": "日期", "mode": "integrated", "sort": {"type": "group", "order": "asc"}}]
        }
    },
    {
        "name": "浅层工作占比趋势",
        "type": "column",
        "data_config": {
            "table_name": TABLE_NAME,
            "series": [{"field_name": "当日浮浅工作占比", "rollup": "AVERAGE"}],
            "group_by": [{"field_name": "日期", "mode": "integrated", "sort": {"type": "group", "order": "asc"}}]
        }
    },
    {
        "name": "心流状态分布",
        "type": "ring",
        "data_config": {
            "table_name": TABLE_NAME,
            "count_all": True,
            "group_by": [{"field_name": "最高心流状态", "mode": "integrated"}]
        }
    },
    {
        "name": "第一勺冰淇淋完成率",
        "type": "ring",
        "data_config": {
            "table_name": TABLE_NAME,
            "count_all": True,
            "group_by": [{"field_name": "第一勺完成", "mode": "integrated"}]
        }
    },
    {
        "name": "干扰次数趋势",
        "type": "column",
        "data_config": {
            "table_name": TABLE_NAME,
            "series": [{"field_name": "干扰次数", "rollup": "SUM"}],
            "group_by": [{"field_name": "日期", "mode": "integrated", "sort": {"type": "group", "order": "asc"}}]
        }
    },
    {
        "name": "冲刺任务总数",
        "type": "statistics",
        "data_config": {
            "table_name": TABLE_NAME,
            "series": [{"field_name": "冲刺任务数", "rollup": "SUM"}]
        }
    },
]


def create_component(comp, index):
    """创建单个仪表盘组件"""
    print(f"\n[{index+1}/{len(COMPONENTS)}] 创建组件: {comp['name']} (type: {comp['type']})")

    # 将 data_config 写入临时文件
    tmp_path = os.path.join(os.path.dirname(__file__), f"_dash_tmp_{index}.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(comp["data_config"], f, ensure_ascii=False)

    try:
        result = subprocess.run(
            [LARK_CLI, "base", "+dashboard-block-create",
             "--base-token", BASE_TOKEN,
             "--dashboard-id", DASHBOARD_ID,
             "--name", comp["name"],
             "--type", comp["type"],
             "--data-config", f"@{os.path.basename(tmp_path)}",
             "--as", "user",
             "--format", "json"],
            capture_output=True, timeout=30,
            cwd=os.path.dirname(__file__),
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )

        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        if result.returncode == 0:
            try:
                resp = json.loads(stdout)
                if resp.get("ok"):
                    block_id = resp.get("data", {}).get("block", {}).get("block_id", "?")
                    print(f"  ✅ 成功 (block_id: {block_id})")
                    return True
                else:
                    print(f"  ❌ API错误: {resp.get('error', stdout[:200])}")
                    return False
            except json.JSONDecodeError:
                print(f"  ❌ JSON解析失败: {stdout[:200]}")
                return False
        else:
            print(f"  ❌ 命令失败: {stderr[:200] or stdout[:200]}")
            return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    print(f"🚀 开始创建仪表盘组件（共 {len(COMPONENTS)} 个）")
    print(f"   Dashboard ID: {DASHBOARD_ID}")

    success_count = 0
    for i, comp in enumerate(COMPONENTS):
        ok = create_component(comp, i)
        if ok:
            success_count += 1
        else:
            print(f"  ⚠️ 组件创建失败，继续下一个...")
        # 串行执行，间隔1秒避免并发
        if i < len(COMPONENTS) - 1:
            time.sleep(1)

    print(f"\n{'='*50}")
    print(f"完成: {success_count}/{len(COMPONENTS)} 个组件创建成功")

    if success_count == len(COMPONENTS):
        print("\n🔄 执行智能布局重排...")
        result = subprocess.run(
            [LARK_CLI, "base", "+dashboard-arrange",
             "--base-token", BASE_TOKEN,
             "--dashboard-id", DASHBOARD_ID,
             "--as", "user", "--format", "json"],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        if result.returncode == 0:
            print("  ✅ 布局重排完成")
        else:
            print(f"  ⚠️ 布局重排失败（不影响组件功能）")

    print(f"\n📊 仪表盘地址: https://my.feishu.cn/base/{BASE_TOKEN}")


if __name__ == "__main__":
    main()
