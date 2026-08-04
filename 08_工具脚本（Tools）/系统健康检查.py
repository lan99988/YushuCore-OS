# -*- coding: utf-8 -*-
"""
系统健康检查.py  —  个人混合管理系统 v1.1 自检入口（第一版，单文件）

设计原则：只观察，不修改。
  - 不自动修复 / 不自动改文件 / 不自动迁移 / 不 AI 诊断
  - 只读文件系统、只读飞书 auth status、只编译不执行业务逻辑
  - 任何修复动作由人决定，脚本只负责暴露问题

检查项（7）：
  1. 目录检查        10 个顶层真实目录存在性
  2. Skill检查       每个 SKILL.md 含 10 个标准信息段
  3. Schema检查      JSON 合法性 + Schema ⊆ 注册表(15 模型)
  4. Python检查      6 引擎 py_compile
  5. Import检查      6 模块跨目录加载
  6. Feishu检查      lark-cli auth status (bot ready)
  7. Automation检查  扫描自动化定义，无旧路径引用

规范：07_系统文档（Docs）/系统健康检查规范.md
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ===== 路径解析：不写死绝对路径，随文件位置自适应 =====
ROOT = Path(__file__).resolve().parent.parent  # 08_工具脚本（Tools） -> 项目根

REQUIRED_DIRS = [
    "00_系统核心（System）",
    "01_Skill能力库（Skills）",
    "02_执行引擎（Engine）",
    "03_领域模块（Modules）",
    "04_数据中心（Data）",
    "05_自动化工作流（Automation）",
    "06_外部连接（Integration）",
    "07_系统文档（Docs）",
    "08_工具脚本（Tools）",
    "09_临时文件（Temp）",
]

REQUIRED_SECTIONS = [
    "基础信息", "功能定位", "触发方式", "输入", "输出",
    "依赖", "数据", "权限", "调用链", "测试",
]

ENGINE_FILES = [
    ("02_执行引擎（Engine）/输入解析引擎/input_parser.py", "input_parser"),
    ("02_执行引擎（Engine）/每日排程引擎/daily_scheduler.py", "daily_scheduler"),
    ("02_执行引擎（Engine）/每日排程引擎/calendar_sync.py", "calendar_sync"),
    ("02_执行引擎（Engine）/数据分析引擎/analytics_engine.py", "analytics_engine"),
    ("02_执行引擎（Engine）/复盘分析引擎/weekly_deep_review.py", "weekly_deep_review"),
    ("03_领域模块（Modules）/比赛管理（Competition）/程序/competition_manager.py", "competition_manager"),
]

# 自动化旧路径禁止模式（重构前失效的相对路径）
STALE_PATTERNS = [
    re.compile(r"scripts/"),
    re.compile(
        r"python\s+[\"']?[^=\"'/\n\\]*\b"
        r"(input_parser|daily_scheduler|calendar_sync|analytics_engine|weekly_deep_review|competition_manager)"
        r"\.py", re.I),
]


class HealthChecker:
    def __init__(self, root_path: Path):
        self.root = root_path
        self.results: list[dict] = []

    def _add(self, name: str, status: str, detail: str, error: str = ""):
        self.results.append({
            "name": name,
            "status": status,      # PASS / FAIL / WARN
            "detail": detail,
            "error": error,
        })

    # ---------- 1. 目录检查 ----------
    def check_directory(self):
        missing = [d for d in REQUIRED_DIRS if not (self.root / d).is_dir()]
        if missing:
            self._add("目录检查", "FAIL", f"缺失 {len(missing)}/{len(REQUIRED_DIRS)}",
                      "缺失目录: " + ", ".join(missing))
        else:
            self._add("目录检查", "PASS", f"{len(REQUIRED_DIRS)}/{len(REQUIRED_DIRS)} 目录存在")

    # ---------- 2. Skill 检查 ----------
    def check_skills(self):
        skill_root = self.root / "01_Skill能力库（Skills）"
        skill_dirs = [p for p in skill_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
        total = len(skill_dirs)
        bad = []
        for d in skill_dirs:
            text = (d / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
            miss = [s for s in REQUIRED_SECTIONS if f"## {s}" not in text]
            if miss:
                bad.append(f"{d.name}→缺失[{','.join(miss)}]")
        if total == 0:
            self._add("Skill检查", "FAIL", "未找到任何 Skill", "01_Skill能力库（Skills） 下无 SKILL.md")
        elif bad:
            self._add("Skill检查", "FAIL", f"{total - len(bad)}/{total} 通过", "; ".join(bad))
        else:
            self._add("Skill检查", "PASS", f"{total}/{total} Skill 含全部 10 标准段")

    # ---------- 3. Schema 检查 ----------
    def _registry_models(self) -> set[str]:
        reg = self.root / "01_Skill能力库（Skills）/yushu_00_Skill注册中心_Registry/SKILL.md"
        if not reg.exists():
            return set()
        text = reg.read_text(encoding="utf-8", errors="ignore")
        # 限制在「数据资产注册表」段内解析
        start = text.find("## 数据资产注册表")
        if start == -1:
            start = 0
        seg = text[start:text.find("\n## ", start + 4)] if "\n## " in text[start:] else text[start:]
        models = set()
        for line in seg.splitlines():
            m = re.match(r"^\s*\|\s*(\d+)\s*\|\s*([A-Za-z][\w]*)\s*\|", line)
            if m:
                models.add(m.group(2))
        return models

    def check_schema(self):
        schema_dir = self.root / "04_数据中心（Data）/数据模型（Schema）"
        jsons = list(schema_dir.rglob("*.json")) if schema_dir.exists() else []
        # 3.1 JSON 合法性
        parse_fail = []
        models = []
        for j in jsons:
            try:
                data = json.load(open(j, encoding="utf-8"))
                if isinstance(data, dict) and data.get("model"):
                    models.append(data["model"])
            except Exception as e:
                parse_fail.append(f"{j.name}: {e}")
        if parse_fail:
            self._add("Schema检查", "FAIL", f"{len(jsons) - len(parse_fail)}/{len(jsons)} JSON 合法",
                      "; ".join(parse_fail))
            return
        # 3.2 注册表一致性 Schema ⊆ Registry
        reg_models = self._registry_models()
        if not reg_models:
            self._add("Schema检查", "WARN", f"{len(jsons)} JSON 合法，但注册表模型未解析",
                      "无法校验 Schema ⊆ Registry")
            return
        orphan = [m for m in models if m not in reg_models]
        if orphan:
            self._add("Schema检查", "FAIL", f"{len(jsons)} JSON 合法，但 {len(orphan)} 个不在注册表",
                      "Schema 模型不在注册表: " + ", ".join(orphan))
        else:
            self._add("Schema检查", "PASS",
                      f"{len(jsons)} JSON 合法；{len(models)} 模型均在注册表({len(reg_models)})内")

    # ---------- 4. Python 引擎检查 ----------
    def check_python(self):
        import py_compile
        fails = []
        for rel, _ in ENGINE_FILES:
            p = self.root / rel
            if not p.exists():
                fails.append(f"{rel}: 文件缺失")
                continue
            try:
                py_compile.compile(str(p), doraise=True)
            except py_compile.PyCompileError as e:
                fails.append(f"{rel}: {e}")
        if fails:
            self._add("Python检查", "FAIL", f"{len(ENGINE_FILES) - len(fails)}/{len(ENGINE_FILES)} 编译通过",
                      "; ".join(fails))
        else:
            self._add("Python检查", "PASS", f"{len(ENGINE_FILES)}/{len(ENGINE_FILES)} 引擎语法编译通过")

    # ---------- 5. Import 检查 ----------
    def check_import(self):
        # 注入各引擎目录，模拟真实运行期 sys.path
        engine_dirs = []
        for rel, _ in ENGINE_FILES:
            d = (self.root / rel).parent
            if d.is_dir() and str(d) not in engine_dirs:
                engine_dirs.append(str(d))
        # competition_manager 在 03 领域模块下
        comp_dir = (self.root / ENGINE_FILES[5][0]).parent
        if comp_dir.is_dir() and str(comp_dir) not in engine_dirs:
            engine_dirs.append(str(comp_dir))
        for d in engine_dirs:
            if d not in sys.path:
                sys.path.insert(0, d)
        fails = []
        for rel, mod in ENGINE_FILES:
            try:
                __import__(mod)
            except Exception as e:
                fails.append(f"{mod}: {type(e).__name__}: {e}")
        if fails:
            self._add("Import检查", "FAIL", f"{len(ENGINE_FILES) - len(fails)}/{len(ENGINE_FILES)} 加载成功",
                      "; ".join(fails))
        else:
            self._add("Import检查", "PASS", f"{len(ENGINE_FILES)}/{len(ENGINE_FILES)} 模块跨目录加载成功")

    # ---------- 6. Feishu 检查 ----------
    def _resolve_lark_cli(self):
        # Windows 上 lark-cli 是 bash 包装脚本，shutil.which 会解析到它但无法直接 exec，
        # 因此优先使用已验证的 node + run.js 路径。
        home = Path.home()
        cli_js = home / ".workbuddy/binaries/node/workspace/node_modules/@larksuite/cli/scripts/run.js"
        node = shutil.which("node")
        if not node:
            for c in [
                home / ".workbuddy/binaries/node/versions/22.22.2/node.exe",
                home / ".workbuddy/binaries/node/versions/26.3.0/node.exe",
            ]:
                if c.exists():
                    node = str(c)
                    break
        if cli_js.exists() and node:
            return [str(node), str(cli_js)]
        # 兜底：仅当 PATH 上存在 .exe/.cmd 形式时才用
        for ext in (".exe", ".cmd"):
            p = shutil.which("lark-cli" + ext)
            if p:
                return [p]
        return None

    def check_feishu(self):
        cli = self._resolve_lark_cli()
        if not cli:
            self._add("Feishu检查", "FAIL", "lark-cli 不可用",
                      "PATH 无 lark-cli，且未找到 node run.js")
            return
        try:
            proc = subprocess.run(
                cli + ["auth", "status"],
                capture_output=True, text=True, timeout=45)
            out = (proc.stdout + proc.stderr).lower()
            if proc.returncode == 0 and "bot" in out and "ready" in out:
                self._add("Feishu检查", "PASS", "bot ready")
            else:
                self._add("Feishu检查", "FAIL", f"exit={proc.returncode}",
                          (proc.stdout + proc.stderr).strip()[-300:])
        except subprocess.TimeoutExpired:
            self._add("Feishu检查", "FAIL", "超时(45s)", "lark-cli auth status 超时（可能 TLS 握手超时，重试可恢复）")
        except Exception as e:
            self._add("Feishu检查", "FAIL", f"异常: {type(e).__name__}", str(e))

    # ---------- 7. Automation 检查 ----------
    def check_automation(self):
        found = []
        root_norm = str(self.root).replace("\\", "/").lower()
        # 7.1 扫描全局 workbuddy.db 的 automations 表（当前定义，不含历史）
        #     —— 按 cwds 限定到本项目，避免误报其他项目 / 历史执行记录(automation_runs)
        db = Path.home() / ".workbuddy" / "workbuddy.db"
        if db.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db))
                cur = conn.cursor()
                cur.execute("SELECT * FROM automations")
                col_names = [d[0] for d in cur.description]
                pidx = col_names.index("prompt") if "prompt" in col_names else None
                cidx = col_names.index("cwds") if "cwds" in col_names else None
                for row in cur.fetchall():
                    prompt = str(row[pidx]) if pidx is not None else " ".join(str(v) for v in row)
                    cwds_raw = row[cidx] if cidx is not None else ""
                    try:
                        cwds = json.loads(cwds_raw) if cwds_raw else []
                    except Exception:
                        cwds = []
                    # 仅检查 cwds 指向本项目的自动化
                    if cwds and not any(root_norm in str(c).replace("\\", "/").lower() for c in cwds):
                        continue
                    for p in STALE_PATTERNS:
                        m = p.search(prompt)
                        if m:
                            found.append(f"automations(prompt): {m.group(0)}")
                conn.close()
            except Exception:
                pass
        # 7.2 扫描磁盘 .workbuddy/automations（junction -> 工作流定义，本项目范围）
        auto_dir = self.root / ".workbuddy" / "automations"
        if auto_dir.exists():
            for f in auto_dir.rglob("*"):
                if f.is_file():
                    try:
                        text = f.read_text(encoding="utf-8", errors="ignore")
                        for p in STALE_PATTERNS:
                            m = p.search(text)
                            if m:
                                found.append(f"{f.name}: {m.group(0)}")
                    except Exception:
                        pass
        if found:
            self._add("Automation检查", "FAIL", "发现旧路径引用", "; ".join(found))
        else:
            self._add("Automation检查", "PASS", "无旧路径引用（automations 表按 cwds 限定本项目）")

    # ---------- 报告 ----------
    def is_healthy(self) -> bool:
        return all(r["status"] in ("PASS", "WARN") for r in self.results) and \
               not any(r["status"] == "FAIL" for r in self.results)

    def report(self):
        lines = []
        lines.append("=" * 32)
        lines.append("")
        lines.append("个人混合管理系统健康报告")
        lines.append("")
        lines.append("时间:")
        lines.append(f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M}")
        lines.append("")
        for r in self.results:
            lines.append(f"{r['name']:<14} {r['status']:<6} {r['detail']}")
            if r["error"]:
                for el in r["error"].split("; "):
                    lines.append(f"    └─ {el}")
        lines.append("")
        status = "READY" if self.is_healthy() else "UNHEALTHY"
        lines.append("System Status:")
        lines.append("")
        lines.append(f"    {status}")
        lines.append("")
        lines.append("=" * 32)
        print("\n".join(lines))


def main():
    checker = HealthChecker(ROOT)
    checker.check_directory()
    checker.check_skills()
    checker.check_schema()
    checker.check_python()
    checker.check_import()
    checker.check_feishu()
    checker.check_automation()
    checker.report()
    sys.exit(0 if checker.is_healthy() else 1)


if __name__ == "__main__":
    main()
