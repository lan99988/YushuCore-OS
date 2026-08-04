"""Competition handler (Step2-4-C-11b) — Adapter 模式。

迁移自 input_parser_old.main() 中的内联懒导入调用（2343-2348）。
薄封装，委托 competition_manager.main_handler() 处理全部比赛业务逻辑。

不复制 competition_manager 内部逻辑，不作为独立业务 handler。
方案 B：set_config 注入源来自 config.py + lark_bridge，非 legacy（input_parser_old）。

依赖链：
  handle_competition -> competition_manager.main_handler -> competition_manager 内部状态机 -> Feishu Base
"""

import os
import sys

from ..config import BASE_TOKEN, TABLES
from ..lark_bridge import _run_lark_cli


def _ensure_competition_path():
    """轻量 sys.path 保护：确保比赛管理模块目录可导入。

    与 input_parser_old._ensure_engine_paths() 的竞争管理器路径一致，
    但自包含，不依赖 legacy。
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    # handlers/ -> 输入解析引擎/ -> 02_执行引擎（Engine）/ -> .. -> 项目根 -> 03_领域模块（Modules）/比赛管理（Competition）/程序/
    _engine_root = os.path.dirname(os.path.dirname(_here))
    _project_root = os.path.dirname(_engine_root)
    _comp_path = os.path.join(
        _project_root,
        "03_领域模块（Modules）",
        "比赛管理（Competition）",
        "程序",
    )
    if os.path.isdir(_comp_path) and _comp_path not in sys.path:
        sys.path.insert(0, _comp_path)


def handle_competition(raw_text, dry_run=False):
    """处理 #比赛 指令：委托 competition_manager.main_handler。

    签名 ``(raw_text, dry_run=False)`` 兼容 router.dispatch 的调用约定。

    薄封装层：
      1. 确保路径可导入
      2. 懒导入 competition_manager
      3. set_config 注入配置（方案 B）
      4. 委托 main_handler 处理
    """
    _ensure_competition_path()
    from competition_manager import main_handler, set_config

    set_config(BASE_TOKEN, TABLES, _run_lark_cli)
    return main_handler(raw_text, dry_run=dry_run)
