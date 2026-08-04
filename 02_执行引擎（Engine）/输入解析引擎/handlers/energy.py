"""Energy status handler (Step2-4-C-2).

迁移自 input_parser_old.handle_energy_status（906-943），1:1 复刻业务逻辑。
本文件只委托标准库，不依赖其他已迁移模块（energy 无网络、无跨模块调用）。
"""

import os
import json
import datetime


def _engine_runtime_path():
    """复刻旧 main 的 ``os.path.dirname(__file__)`` 语义（关键路径保护）。

    旧代码位于 ``输入解析引擎/`` 根，故用 ``dirname(__file__)`` 得到引擎根，
    再拼 ``runtime/_energy_status.json``（该 ``runtime`` 是 junction，
    指向共享 ``04_数据中心/运行状态（Runtime）``）。

    本 handler 位于 ``输入解析引擎/handlers/``，若直接用 ``dirname(__file__)``
    会错误落到 ``handlers/runtime/``（非 junction，每日排程引擎读不到）。
    因此须上溯两级回到引擎根，保持与旧代码**逐字一致**的物理写入目标。
    """
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_dir, "runtime", "_energy_status.json")


def handle_energy_status(raw_text, dry_run=False):
    """处理 #精力 指令。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定
    ``handler(raw_text, dry_run=dry_run)``；dry_run 旧逻辑无分支，故忽略
    （与旧 ``_call_energy`` 透传一致，不引入 dry_run 行为差）。
    """
    content = raw_text.replace("#精力", "").strip()
    today = datetime.datetime.now().strftime("%Y/%m/%d")

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

    # 写入临时记录到固定文件（与旧 main 相同物理路径）
    energy_file = _engine_runtime_path()
    try:
        with open(energy_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                    "status": energy_status,
                    "raw": content,
                },
                f,
                ensure_ascii=False,
            )
    except IOError:
        pass

    return {
        "ok": True,
        "type": "energy_status",
        "message": f"【{today}】精力状态：{energy_status}（原始反馈：{content}）",
        "suggestion": "精力系数已设为0.8，明日可用时长将缩减"
        if energy_status == "差"
        else ("精力系数已设为1.2，明日精力充沛" if energy_status == "好" else None),
    }
