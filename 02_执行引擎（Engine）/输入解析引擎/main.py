"""
输入解析引擎正式入口（Step2-5a）

替代旧 input_parser.main()（2395 行巨石），
通过 router.dispatch() 完成分发。

cli 用法（与旧 input_parser.py 一致）：
    python main.py "#任务 做数学真题 【项目：数学二】"
    python main.py "#习惯 每天背20个单词" --dry-run

设计原则：
- 不复制业务逻辑
- 不包装 dispatch（dispatch 内部已处理 print + sys.exit）
- 仅做 CLI 参数解析 + dispatch 调用
"""

import os
import sys

# ============ 引擎包路径注册 ============
# 使 `from 输入解析引擎.router import dispatch` 可工作
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PARENT = os.path.dirname(HERE)  # 02_执行引擎（Engine）
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)


def main():
    """入口：解析参数 → dispatch。

    与旧 input_parser.main() 等价：
      - 无参数 → 打印用法并 exit(1)
      - 含 --dry-run → 测试模式
      - dispatch 内部处理 print + sys.exit
    """
    if len(sys.argv) < 2:
        print("用法：python main.py \"<消息文本>\" [--dry-run]")
        print("示例：python main.py \"#任务 做数学真题 【项目：数学二】【精力：高】\"")
        sys.exit(1)

    # 处理参数
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    raw_text = " ".join(args)

    # 分发（dispatch 内部处理所有 print + sys.exit）
    from 输入解析引擎.router import dispatch
    dispatch(raw_text, dry_run=dry_run)


if __name__ == "__main__":
    main()
