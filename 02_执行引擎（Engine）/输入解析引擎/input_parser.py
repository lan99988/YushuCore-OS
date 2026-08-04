#!/usr/bin/env python3
"""
个人混合管理系统 - 输入解析引擎 (v1.2)
=========================================
Shim — 委托 main.py 中的真实入口。
旧 2395 行逻辑已拆分为 Router + 17 handlers。
旧行为基准保留在 input_parser_old.py (Frozen Reference)。
"""
from main import main

if __name__ == "__main__":
    main()
