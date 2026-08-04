"""Config command handler (Step2-4-C-3).

迁移自 input_parser_old.handle_config（946-997），1:1 复刻业务逻辑。
本文件只委托标准库（re/os/json），不依赖其他已迁移模块、无网络调用。
"""

import os
import re
import json


def _engine_runtime_path():
    """复刻旧 main 的 ``os.path.dirname(__file__)`` 语义（关键路径保护）。

    旧代码位于 ``输入解析引擎/`` 根，故用 ``dirname(__file__)`` 得到引擎根，
    再拼 ``runtime/_schedule_config.json``（该 ``runtime`` 是 junction，
    指向共享 ``04_数据中心/运行状态（Runtime）``）。

    本 handler 位于 ``输入解析引擎/handlers/``，若直接用 ``dirname(__file__)``
    会错误落到 ``handlers/runtime/``（非 junction，每日排程引擎读不到）。
    因此须上溯两级回到引擎根，保持与旧代码**逐字一致**的物理写入目标。
    """
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_dir, "runtime", "_schedule_config.json")


def handle_config_cmd(raw_text, dry_run=False):
    """处理 #配置 指令。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``；dry_run 旧逻辑无分支，故忽略
    （与旧 ``_call_config_cmd`` 透传一致，不引入 dry_run 行为差）。
    """
    content = raw_text.replace("#配置", "").strip()

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
        config_file = _engine_runtime_path()
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
