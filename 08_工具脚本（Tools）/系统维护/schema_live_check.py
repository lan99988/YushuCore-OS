#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schema_live_check.py —— Schema Center 只读检查器（Phase 2-B-1 · Step 1）

目的：把本地 Schema 定义（04_数据中心/数据模型（Schema）/**/*.json）与
      "live 表结构"对照，输出漂移(diff)报告。

数据来源（source）：
  - 默认 doc：读取 live_reference.json（由 SYSTEM_BLUEPRINT.md 手工转录的 live 表结构）。
  - --live   ：尝试用 lark-cli base +field-list 拉真实飞书表字段覆盖 doc 基准（best-effort）。

纪律：本脚本【只读】。绝不调用任何写接口（field-update / record-upsert 一律不动），
      不修改任何 schema JSON，不修改 live 表结构。

对比键：字段以 中文名称(cn) 匹配；enum 以 options 集合比较（顺序无关）。
输出：Markdown 报告到 stdout；可加 --out <file> 落盘（仅写报告文件，不碰 schema）。
"""
import argparse
import json
import os
import glob
import subprocess
import sys

# ---- 路径默认值（相对本脚本所在目录定位目标项目根） ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 本脚本位于 <root>/08_工具脚本（Tools）/系统维护/，上两级是项目根
DEFAULT_PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_SCHEMA_DIR = os.path.join(
    DEFAULT_PROJECT_ROOT,
    "04_数据中心（Data）", "数据模型（Schema）"
)
DEFAULT_REF = os.path.join(SCRIPT_DIR, "live_reference.json")

LARK_CLI = "/c/Users/26326/.workbuddy/binaries/node/cli-connector-packages/lark-cli"
BASE_TOKEN = "TtzIboiQQaPgfVszO2vc56wLnof"


def load_local_schemas(schema_dir):
    """读取所有本地 schema JSON，按 model 名索引。"""
    schemas = {}
    paths = sorted(glob.glob(os.path.join(schema_dir, "**", "*.json"), recursive=True))
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] 无法解析 {p}: {e}", file=sys.stderr)
            continue
        model = data.get("model")
        if not model:
            continue
        schemas[model] = {"path": p, "data": data}
    return schemas


def load_reference(ref_path):
    with open(ref_path, "r", encoding="utf-8") as f:
        return json.load(f)


def field_index(fields):
    """cn -> options(set)。

    键名统一取中文名：本地 schema 字段用 `中文名称`，live_reference 用 `cn`；
    二者互斥，互作回退，确保中文名能对上（否则英文键名 vs 中文键名会 100% 假漂移）。
    """
    idx = {}
    for fld in fields:
        cn = fld.get("cn") or fld.get("中文名称") or fld.get("name")
        if not cn:
            continue
        opts = fld.get("options") or []
        idx[cn] = set(opts)
    return idx


def compare_schema(model, local, ref_entry):
    """返回 diff 字典。"""
    local_fields = local["data"].get("fields", [])
    local_idx = field_index(local_fields)
    ref_fields = ref_entry.get("fields", [])
    ref_idx = field_index(ref_fields)

    local_cns = set(local_idx.keys())
    ref_cns = set(ref_idx.keys())

    missing_in_local = sorted(ref_cns - local_cns)   # live 有、本地缺
    extra_in_local = sorted(local_cns - ref_cns)      # 本地有、live 无
    common = sorted(local_cns & ref_cns)

    enum_drifts = []
    for cn in common:
        lo = local_idx[cn]
        ro = ref_idx[cn]
        # 仅当至少一侧有 options 才比较
        if not lo and not ro:
            continue
        if lo != ro:
            enum_drifts.append({
                "field": cn,
                "local": sorted(lo),
                "live": sorted(ro),
            })

    # 状态判定
    has_drift = bool(missing_in_local or extra_in_local or enum_drifts)
    status = "OK" if not has_drift else "DRIFT"
    return {
        "model": model,
        "status": status,
        "missing_in_local": missing_in_local,
        "extra_in_local": extra_in_local,
        "enum_drifts": enum_drifts,
    }


def try_live_override(ref, schemas):
    """best-effort：用 lark-cli 拉真实字段覆盖 doc 基准。失败则返回原 ref + 错误。"""
    errors = []
    for model, entry in ref["models"].items():
        tid = entry.get("feishu_table_id")
        if not tid:
            continue
        try:
            out = subprocess.run(
                [LARK_CLI, "base", "+field-list",
                 "--base-token=" + BASE_TOKEN, "--table-id=" + tid, "--as=user"],
                capture_output=True, text=True, timeout=30
            )
            if out.returncode != 0:
                errors.append(f"{model}({tid}): rc={out.returncode} {out.stderr.strip()[:120]}")
                continue
            # TODO: 解析 out.stdout 的字段 JSON，转成 fields 结构覆盖 entry["fields"]
            # 因 lark-cli 输出格式需实测，此处先记录"未实现解析"，保留 doc 基准。
            errors.append(f"{model}({tid}): lark-cli 调用成功，但输出解析未实现，仍用 doc 基准")
        except Exception as e:
            errors.append(f"{model}({tid}): {e}")
    return ref, errors


def main():
    ap = argparse.ArgumentParser(description="Schema Center 只读检查器")
    ap.add_argument("--schema-dir", default=DEFAULT_SCHEMA_DIR)
    ap.add_argument("--reference", default=DEFAULT_REF)
    ap.add_argument("--out", default=None, help="报告落盘路径（仅写报告文件）")
    ap.add_argument("--live", action="store_true", help="尝试用 lark-cli 拉真实字段（best-effort）")
    args = ap.parse_args()

    schemas = load_local_schemas(args.schema_dir)
    ref = load_reference(args.reference)

    source_label = f"doc({os.path.basename(args.reference)})"
    live_errors = []
    if args.live:
        ref, live_errors = try_live_override(ref, schemas)
        source_label = "live(lark-cli)+doc 回退"

    lines = []
    lines.append(f"# Schema–Live 对照报告")
    lines.append("")
    lines.append(f"- 数据来源：{source_label}")
    lines.append(f"- 本地 schema 目录：`{args.schema_dir}`")
    lines.append("")
    lines.append("> ⚠️ 本报告为【只读】检查产出，未对任何 schema / 飞书表执行写操作。")
    lines.append("")
    lines.append("**置信度说明**：")
    lines.append("- 🔴 **enum 漂移 = 高置信**：本地 schema 的 `note` 自承『enum options 为初版，待与飞书实表对齐』，且 blueprint 明确记录了 live 枚举（如 P0-P3）。")
    lines.append("- 🟡 **字段存在性差异 = 中置信**：live_reference 由 SYSTEM_BLUEPRINT.md 手工转录，computed 时间戳（创建时间/最后修改时间/ID）等可能有转录出入，需 `--live` 真机复核。")
    lines.append("- 📝 **NO LIVE TABLE**：design_draft 或规划项，无对应 live 表，跳过字段/枚举比对。")
    lines.append("")

    summary = {"present": 0, "missing": 0, "ok": 0, "drift": 0}
    missing_list = []
    drift_lines = []

    for model, entry in ref["models"].items():
        cat = entry.get("category", "?")
        if model not in schemas:
            summary["missing"] += 1
            missing_list.append((model, cat, entry.get("feishu_table_name")))
            lines.append(f"## ❌ MISSING SCHEMA：{model}")
            lines.append(f"- 目标目录：`{cat}/`")
            lines.append(f"- live 表：{entry.get('feishu_table_name')} ({entry.get('feishu_table_id')})")
            note = entry.get("note")
            if note:
                lines.append(f"- 备注：{note}")
            lines.append("")
            continue

        summary["present"] += 1

        # design_draft / 规划项：无 live 表，跳过比对
        if entry.get("feishu_table_id") is None:
            lines.append(f"## 📝 NO LIVE TABLE：{model}")
            lines.append(f"- 目录：`{cat}/`")
            lines.append(f"- 备注：{entry.get('note') or '无对应 live 表，跳过字段/枚举比对'}")
            lines.append("")
            continue

        d = compare_schema(model, schemas[model], entry)
        if d["status"] == "OK":
            summary["ok"] += 1
            tag = "✅ OK"
        else:
            summary["drift"] += 1
            tag = "⚠️ DRIFT"
        lines.append(f"## {tag}：{model}")
        lines.append(f"- 文件：`{os.path.relpath(schemas[model]['path'], DEFAULT_PROJECT_ROOT)}`")
        if d["missing_in_local"]:
            lines.append(f"- **live 有、本地缺字段**：{', '.join(d['missing_in_local'])}")
        if d["extra_in_local"]:
            lines.append(f"- **本地有、live 无字段**：{', '.join(d['extra_in_local'])}")
        if d["enum_drifts"]:
            lines.append(f"- **enum 漂移（{len(d['enum_drifts'])} 处）**：")
            for ed in d["enum_drifts"]:
                lines.append(f"  - `{ed['field']}`")
                lines.append(f"    - 本地：{ed['local']}")
                lines.append(f"    - live：{ed['live']}")
        if d["status"] == "OK":
            lines.append("- 字段与 enum 未发现漂移。")
        lines.append("")

    # 汇总
    total = len(ref["models"])
    lines.insert(0, (
        f"**汇总**：期望 {total} 个 schema ｜ 本地存在 {summary['present']} ｜ "
        f"缺失 {summary['missing']} ｜ 存在且无漂移 {summary['ok']} ｜ 存在但有漂移 {summary['drift']}"
    ))
    lines.insert(1, "")

    if missing_list:
        lines.append("## 缺失 schema 清单（需 Step 2 补齐）")
        for m, c, tname in missing_list:
            lines.append(f"- `{m}` → 目录 `{c}/`（live 表：{tname}）")
        lines.append("")

    if live_errors:
        lines.append("## --live 模式注记")
        for e in live_errors:
            lines.append(f"- {e}")
        lines.append("")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[INFO] 报告已写至 {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
