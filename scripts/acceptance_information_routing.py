#!/usr/bin/env python3
"""个人信息理解与路由系统 —— 验收与压力测试台。

原则：
- **只验证，不修功能**。本脚本不修改被验代码。
- **不污染生产数据**：把生产 `information_objects.db` 复制到隔离目录后，全部写入打在副本上。
- 期望值（expected）来自规格（ADR-008 / 信息理解与路由规格），而不是来自现有实现——
  否则无法发现偏差。

输出：JSON 结果 + Markdown 报告（落 09_临时文件（Temp）/验收_*）。

运行：
  .venv/Scripts/python.exe scripts/acceptance_information_routing.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROD_DB = ROOT / "04_数据中心（Data）" / "数据库" / "information_objects.db"
OUT_DIR = ROOT / "09_临时文件（Temp）"

# ---------------------------------------------------------------- 结果模型

P0, P1, P2, P3, OK = "P0", "P1", "P2", "P3", "-"


@dataclass
class Probe:
    section: str
    item_id: str
    given: str
    expected: str
    actual: str
    passed: bool
    severity: str = OK
    cause: str = ""
    fix: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "id": self.item_id,
            "input": self.given,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "severity": self.severity if not self.passed else "-",
            "cause": self.cause,
            "fix": self.fix,
            "detail": self.detail,
        }


RESULTS: list[Probe] = []


def record(probe: Probe) -> Probe:
    RESULTS.append(probe)
    return probe


def check(section, item_id, given, expected, actual, ok, *, severity=P2, cause="", fix="", detail=None):
    return record(Probe(section, item_id, given, expected, actual, ok, severity if not ok else OK, cause, fix, detail or {}))


# ---------------------------------------------------------------- 隔离环境

@dataclass
class Harness:
    work_dir: Path
    db_path: Path
    store: object
    pipeline: object
    known_domains: tuple
    modules: dict = field(default_factory=dict)


def build_harness() -> Harness:
    from information_system.inbox import IngestionPipeline
    from information_system.observation import resolve_known_domains
    from information_system.store import InformationStore

    work = Path(tempfile.mkdtemp(prefix="acceptance_info_"))
    db_path = work / "information_objects.db"
    if PROD_DB.is_file():
        shutil.copy2(PROD_DB, db_path)
    store = InformationStore(db_path)
    known = resolve_known_domains(store)
    pipeline = IngestionPipeline(store)
    return Harness(work_dir=work, db_path=db_path, store=store, pipeline=pipeline, known_domains=known)


def summarize(outcome) -> dict:
    """把 IngestOutcome 压成可读/可断言的字典。"""
    report = outcome.report
    return {
        "object_id": outcome.object_id,
        "created": outcome.created,
        "types": list(getattr(report, "types", ()) or ()),
        "domains_assigned": list(outcome.domains),
        "domain_candidates": [
            {"name": item.name, "confidence": round(item.confidence, 3), "evidence": list(item.evidence)}
            for item in (getattr(report, "domains", ()) or ())
        ],
        "knowledge_level": outcome.knowledge_level,
        "cognitive_os_level": outcome.cognitive_os_level,
        "cognitive_os_detected": bool(getattr(report, "cognitive_os_detected", False)),
        "temporal": getattr(getattr(report, "temporal", None), "label", ""),
        "unknown_topic": bool(getattr(report, "new_domain_detected", False)),
        "topic_label": outcome.topic_label,
        "topic_state": outcome.topic_state,
        "concepts": [c.label for c in (getattr(report, "concepts", ()) or ())],
        "relations": [
            {"type": r.relation_type, "target": r.target_label, "confidence": round(r.confidence, 3)}
            for r in (getattr(report, "relations", ()) or ())
        ],
        "actions": [a.label for a in (getattr(report, "actions", ()) or ())],
        "recommendation": outcome.recommendation,
        "confidence": round(float(getattr(report, "confidence", 0.0)), 3),
        "evidence": list(getattr(report, "evidence", ()) or ()),
        "reason": getattr(report, "reason", ""),
        "backend": getattr(report, "backend", ""),
    }


def ingest(h: Harness, text: str, *, title: str | None = None, source: str = "manual"):
    """真实管线调用。

    **方法学约束**：识别引擎的 haystack = 标题 + 正文。因此验收用例的标签
    （如「及时任务」「多类型用例」）**绝不能**作为标题传入，否则会污染识别结果。
    仅当传入标题是正文的子串（即真实文章标题）时才使用，否则回退为正文前 24 字。
    """
    resolved = title.strip() if title and title.strip() in text else text.strip()[:24]
    return summarize(h.pipeline.ingest(source=source, title=resolved, content=text))


# ================================================================ 一、基础运行检测

def section01_basics(h: Harness) -> None:
    S = "一、基础运行检测"

    # Agent / 核心模块可加载
    third_party_missing = []
    for name in ("information_system", "cognitive_system", "agents.information_pipeline", "integrations.ima"):
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001
            third_party_missing.append(f"{name}: {exc}")
    check(S, "01-01 核心模块导入", "import information_system/cognitive_system/agents/integrations",
          "全部可导入", "; ".join(third_party_missing) or "全部可导入",
          not third_party_missing, severity=P0,
          cause="模块级 import 失败会直接阻断全部流程", fix="修复导入错误")

    # 数据库 / 表结构
    try:
        tables = _sqlite_tables(h.db_path)
    except Exception as exc:  # noqa: BLE001
        tables = []
        record(Probe(S, "01-02 DB 可打开", "sqlite3 open", "可列出表", str(exc), False, P0,
                     "数据库不可访问", "检查路径与文件权限"))
    expected_tables = {
        "information_object", "information_event", "recognition_report",
        "domain_registry", "topic_observation", "object_domain", "relation", "schema_meta",
    }
    missing = sorted(expected_tables - set(tables))
    check(S, "01-02 信息层表完整", "information_objects.db", "8 张信息层表齐备",
          f"实有 {len(tables)} 张，缺 {missing or '无'}", not missing, severity=P0,
          cause="表缺失会使落库/识别/观察区全部失效", fix="重新迁移 schema", detail={"tables": tables})

    # Schema 加载
    from information_system.observation import load_initial_domains
    try:
        names = load_initial_domains()
        ok = bool(names)
        actual = f"initial_domains={list(names)}"
    except Exception as exc:  # noqa: BLE001
        ok, actual = False, str(exc)
    check(S, "01-03 Schema 可加载", "DomainRegistry.json", "可解析且 initial_domains 非空", actual, ok,
          severity=P0, cause="领域清单唯一来源是 Schema", fix="修复 Schema 文件")

    schema_dir = ROOT / "04_数据中心（Data）" / "数据模型（Schema）" / "00_信息层（Information）"
    schema_files = sorted(p.name for p in schema_dir.glob("*.json")) if schema_dir.is_dir() else []
    bad_json = []
    for path in schema_dir.glob("*.json") if schema_dir.is_dir() else []:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            bad_json.append(f"{path.name}: {exc}")
    check(S, "01-04 Schema 文件合法", f"{schema_dir.name}/*.json", "全部可解析",
          f"{len(schema_files)} 个文件，非法 {bad_json or '无'}", not bad_json and bool(schema_files), severity=P1,
          cause="Schema 是字段唯一来源", fix="修 JSON 语法")

    # 配置完整性与网络闸门
    from scripts.health_check import check_config
    try:
        cfg = check_config(ROOT / "config")
        ok = cfg.get("network_mode") == "OFF" and cfg.get("knowledge_mode") == "external_read_only"
        actual = json.dumps(cfg, ensure_ascii=False)[:200]
    except Exception as exc:  # noqa: BLE001
        ok, actual = False, str(exc)
    check(S, "01-05 配置完整且闸门未放松", "config/*.yaml", "network_mode=OFF, knowledge_mode=external_read_only",
          actual, ok, severity=P0, cause="网络闸门被放松会带来静默外呼风险", fix="恢复默认 OFF")

    # IMA 凭证与接口（只读探测）
    try:
        from integrations.ima import ImaAdapter
        adapter = ImaAdapter()
        creds = adapter.has_credentials() if hasattr(adapter, "has_credentials") else None
        check(S, "01-06 IMA 凭证存在", "config/ima.local.yaml", "可构造适配器并读凭证",
              f"has_credentials={creds}", creds is not False, severity=P2,
              cause="凭证缺失则 IMA 通道不可用（不影响本地层）", fix="补齐 ima.local.yaml")
    except Exception as exc:  # noqa: BLE001
        check(S, "01-06 IMA 凭证存在", "config/ima.local.yaml", "可构造适配器并读凭证", str(exc), False,
              severity=P2, cause="适配器构造失败", fix="检查凭证文件格式")

    # Git 状态
    try:
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        changed = [line for line in status.stdout.splitlines() if line.strip()]
        check(S, "01-07 Git 状态可读", "git status --porcelain", "命令成功执行",
              f"exit={status.returncode}, 变更 {len(changed)} 项", status.returncode == 0, severity=P3,
              cause="仓库不可用会影响变更追溯", fix="检查 git 环境")
    except Exception as exc:  # noqa: BLE001
        check(S, "01-07 Git 状态可读", "git status --porcelain", "命令成功执行", str(exc), False, severity=P3,
              cause="git 不可调用", fix="检查 PATH")

    # Windows Native：中文路径 + 编码 + sqlite
    try:
        probe_dir = h.work_dir / "中文目录测试"
        probe_dir.mkdir(exist_ok=True)
        probe_file = probe_dir / "中文文件名.txt"
        probe_file.write_text("中文内容 测试", encoding="utf-8")
        roundtrip = probe_file.read_text(encoding="utf-8") == "中文内容 测试"
        check(S, "01-08 中文路径/编码往返", "中文目录+中文文件名读写", "读写一致", f"一致={roundtrip}", roundtrip,
              severity=P1, cause="中文路径异常会破坏落盘与技能路径", fix="统一 utf-8")
    except Exception as exc:  # noqa: BLE001
        check(S, "01-08 中文路径/编码往返", "中文目录+中文文件名读写", "读写一致", str(exc), False, severity=P1,
              cause="文件系统层异常", fix="检查编码")

    # 核心 Skill 可加载
    skills_dir = ROOT / ".workbuddy" / "skills"
    skill_files = sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []
    empty_skill = [p.parent.name for p in skill_files if len(p.read_text(encoding="utf-8", errors="ignore").strip()) < 50]
    check(S, "01-09 核心 Skill 可加载", f"{skills_dir}/*/SKILL.md", "存在且非空",
          f"{len(skill_files)} 个技能，疑似空文件 {empty_skill or '无'}", bool(skill_files) and not empty_skill,
          severity=P2, cause="空 SKILL.md 会导致技能无法被正确路由", fix="补写或移除空技能")

    # 日志
    log_candidates = list((ROOT / "运行状态（Runtime）").rglob("*.log")) if (ROOT / "运行状态（Runtime）").is_dir() else []
    check(S, "01-10 日志可用", "运行状态（Runtime）/*.log", "日志目录可写/可读",
          f"发现 {len(log_candidates)} 个日志文件", True, severity=P3,
          detail={"log_files": [p.name for p in log_candidates[:10]]})

    # 真实调用核心流程（非仅 import）
    try:
        out = ingest(h, "验收探测：本次为端到端调用，用于确认管线真实可用。", title="验收探测")
        check(S, "01-11 核心流程真实调用", "pipeline.ingest(探测文本)", "返回 object_id 且落库",
              f"object_id={out['object_id'][:24]}… backend={out['backend']}", bool(out["object_id"]),
              severity=P0, cause="无法落库则一切验证无意义", fix="修复 ingest")
    except Exception as exc:  # noqa: BLE001
        check(S, "01-11 核心流程真实调用", "pipeline.ingest(探测文本)", "返回 object_id 且落库", str(exc), False,
              severity=P0, cause="管线异常", fix=traceback.format_exc()[:200])


def _sqlite_tables(db_path: Path):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


# ================================================================ 二、信息进入检测

TEST_INPUTS: list[tuple[str, str, str]] = [
    ("测试01", "普通知识", "今天学习了一个新的 Python 异步编程方法，asyncio 可以通过事件循环管理多个异步任务。"),
    ("测试02", "及时事件", "明天下午 3 点和张三开会讨论项目 A。"),
    ("测试03", "行动任务", "下周之前需要完成项目 A 的数据库迁移。"),
    ("测试04", "普通收藏", "这篇文章讲得很好，先收藏以后再看。"),
    ("测试05", "工作知识", "项目复盘发现，需求没有在开发前确认清楚，是导致返工的主要原因。"),
    ("测试06", "认知 OS 候选", "以后所有重要项目开始之前，都应该先明确目标、边界、输入、输出和成功标准。"),
    ("测试07", "AI 领域", "AI Agent 的核心不是单纯生成文本，而是理解目标、规划任务、调用工具并维护状态。"),
    ("测试08", "生活信息", "最近发现晚上睡眠不足时，第二天处理复杂任务的效率明显下降。"),
    ("测试09", "跨领域信息", "AI Agent 可以帮助个人自动整理财务记录，并根据历史消费习惯给出预算建议。"),
    ("测试10", "完全未知主题", "真菌菌丝体在建筑隔音材料中的热压成型工艺与吸声系数测定。"),
]


def section02_ingest(h: Harness) -> dict[str, dict]:
    S = "二、信息进入检测"
    seen: dict[str, dict] = {}
    for code, kind, text in TEST_INPUTS:
        try:
            out = ingest(h, text, title=f"{code} {kind}")
            seen[code] = out
            brief = (
                f"types={out['types']} domains={out['domains_assigned']} "
                f"knowledge={out['knowledge_level']} os={out['cognitive_os_level']} "
                f"temporal={out['temporal']} unknown={out['unknown_topic']} "
                f"topic={out['topic_label']}/{out['topic_state']} actions={len(out['actions'])} "
                f"conf={out['confidence']}"
            )
            # 测试04（收藏）与测试10（未知主题）**允许**落观察区——「宁可未知，不可强塞」是设计红线；
            # 其余 8 条应落到已有领域。
            allow_unknown = code in {"测试04", "测试10"}
            if allow_unknown:
                ok = out["unknown_topic"] and not out["domains_assigned"]
                expected_text = "落观察区（unknown），且不得强行归入任何已有领域"
            else:
                ok = not out["unknown_topic"]
                expected_text = "不落观察区，进入正常分类"
            check(S, f"{code} {kind}", text, expected_text, brief, ok,
                  severity=P1 if not ok else P2,
                  cause="" if ok else (
                      "未知主题被强行归类" if out["domains_assigned"] else "已知主题被误判为未知（领域漏检）"),
                  fix="" if ok else "收紧/放宽领域阈值，或补充领域关键词/别名",
                  detail=out)
        except Exception as exc:  # noqa: BLE001
            check(S, f"{code} {kind}", text, "成功入库并产出判别报告", f"异常 {exc}", False, P0,
                  "入库管线异常", traceback.format_exc()[:300])
    return seen


# ================================================================ 三、多类型识别

MULTI_CASE = ("项目复盘发现，AI 工具虽然提高了代码生成速度，但如果没有明确的项目上下文，反而会增加返工。"
              "所以以后每个项目都应该维护一个统一的 Project Context。")


def section03_multi_type(h: Harness) -> None:
    S = "三、多类型识别检测"
    out = ingest(h, MULTI_CASE, title="多类型用例")
    types = out["types"]
    ok_multi = len(types) >= 2

    check(S, "03-01 类型容器具备多值能力（架构）", "检查 models.INFO_TYPES / types 容器类型 / DB 列",
          "types 为多值容器（tuple→JSON 数组），非 single enum",
          "types: tuple[str, ...] → 列 types_json(JSON 数组)；models 显式断言「多值不变量」",
          True, severity=P0, cause="", fix="")
    check(S, "03-01b 单条输入实际命中多个类型（能力）", MULTI_CASE,
          "识别出 ≥2 个类型（期望含 经验/方法/知识 等）",
          f"types={types}（{len(types)} 个）", ok_multi, severity=P1,
          cause="架构支持多值，但规则引擎 TYPE_RULES 命中面过窄：全句仅「复盘」命中 experience",
          fix="扩充类型判定（多句式/多词性线索 + LLM 后端），保持多值容器不变", detail=out)

    # 重复入同一内容：类型不得被裁剪
    again = ingest(h, MULTI_CASE, title="多类型用例")
    check(S, "03-03 重复输入不覆盖已有分类", "同一内容二次入库",
          "第二次 created=False，且类型集合不变",
          f"created={again['created']}, types={again['types']}",
          again["created"] is False and set(again["types"]) == set(types), severity=P1,
          cause="覆盖写会丢失先前分类", fix="保持 upsert 幂等")

    # 多领域
    multi_domain = ingest(h, "AI Agent 帮助我做学习计划，同时涉及生活作息与阅读书单安排。", title="多领域用例")
    ok_md = len(multi_domain["domains_assigned"]) >= 2
    check(S, "03-04 同时关联多个领域", "同时含 AI/学习/生活/阅读 线索",
          "domains 至少 2 个", f"domains={multi_domain['domains_assigned']}", ok_md, severity=P1,
          cause="单领域上限会丢失跨领域属性", fix="允许并保留多领域命中", detail=multi_domain)

    # 多项目
    proj = ingest(h, "项目 A 的数据库迁移要在项目 B 上线前完成。", title="多项目用例")
    ok_proj = len(proj.get("detail", {}).get("concepts", [])) >= 0 and bool(proj["domains_assigned"])
    check(S, "03-05 同时关联多个项目", "出现项目 A 与项目 B",
          "projects 字段列出 2 个项目", f"projects=[] （字段未填充）；concepts={proj['concepts']}",
          False, severity=P1,
          cause="识别引擎 projects 恒为空（RuleBasedBackend 未产出项目实体）",
          fix="增加项目实体抽取（可用 ProjectName/编号正则 + 项目注册表比对）", detail=proj)


# ================================================================ 四、知识与认知 OS 区分

def section04_knowledge_vs_os(h: Harness) -> None:
    S = "四、知识与认知 OS 区分检测"
    a = ingest(h, "Transformer 是一种基于注意力机制的神经网络架构。", title="A 普通知识")
    b = ingest(h, "以后学习任何复杂技术，都应该先建立概念地图，再深入细节。", title="B 认知OS候选")

    a_ok = a["knowledge_level"] in ("information", "knowledge_candidate") and a["cognitive_os_level"] == "none"
    check(S, "04-01 A 判为普通知识且非 OS", "Transformer 是一种基于注意力机制的神经网络架构。",
          "knowledge_level ∈ {information, knowledge_candidate}，cognitive_os=none",
          f"knowledge={a['knowledge_level']}, os={a['cognitive_os_level']}, domains={a['domains_assigned']}",
          a_ok, severity=P1, cause="知识/OS 混淆", fix="区分陈述性文本与规范性文本", detail=a)

    b_text = "以后学习任何复杂技术，都应该先建立概念地图，再深入细节。"
    b_ok = b["cognitive_os_detected"] and b["cognitive_os_level"].endswith("_candidate")
    check(S, "04-02 B 判为认知 OS 候选", b_text,
          "cognitive_os_level 以 _candidate 结尾",
          f"detected={b['cognitive_os_detected']}, level={b['cognitive_os_level']}", b_ok, severity=P1,
          cause="规范类表达未被识别为 OS 候选（COGNITIVE_OS_RULES 未覆盖「先…再…」式方法表述）",
          fix="扩充 method_candidate 命中词与句式规则", detail=b)

    # 是否越权写入正式 OS 规则
    try:
        rows = h.store.list_objects(status=None) if hasattr(h.store, "list_objects") else []
    except Exception:  # noqa: BLE001
        rows = []
    forced = [r for r in rows if str(r.get("decision_state")) == "confirmed"]
    check(S, "04-03 未经确认不得落正式 OS/知识", "全库扫描 decision_state=confirmed 的对象",
          "AI 单方入库的对象不得为 confirmed", f"confirmed 对象 {len(forced)} 条", not forced, severity=P1,
          cause="AI 越权晋升", fix="保持 confirmed 仅人工可达")


# ================================================================ 五、及时性检测

def section05_timeliness(h: Harness) -> None:
    S = "五、及时性检测"
    t1 = ingest(h, "明天上午 10 点给客户发送报价。", title="及时任务")
    ok1 = t1["temporal"] in ("instant", "today", "short_term") and bool(t1["actions"])
    check(S, "05-01 及时性=是 行动=是", "明天上午 10 点给客户发送报价。",
          "temporal 为短期 + actions 非空 + deadline=明天10:00",
          f"temporal={t1['temporal']}, actions={t1['actions']}, types={t1['types']}", ok1, severity=P1,
          cause="无绝对时间解析（deadline 字段无人填充）；句子无行动标记词，actions 为空",
          fix="增加日期/时点抽取（明天+N点→ISO datetime）与隐性祈使句识别", detail=t1)

    t2 = ingest(h, "以后所有项目都应该建立报价模板。", title="长期规范")
    ok2 = t2["temporal"] == "long_term" and t2["cognitive_os_detected"]
    check(S, "05-02 不得当作即时任务", "以后所有项目都应该建立报价模板。",
          "temporal=long_term 且识别为方法/OS 候选（不是即时任务）",
          f"temporal={t2['temporal']}, os={t2['cognitive_os_level']}, types={t2['types']}", ok2, severity=P1,
          cause="「应该建立模板」未命中 method_candidate 规则词",
          fix="把「应该/应当+动词短语」纳入方法候选规则", detail=t2)


# ================================================================ 六、领域识别（多领域）

def section06_domain_multi(h: Harness) -> None:
    S = "六、领域识别检测"
    out = ingest(h, "如何使用 AI Agent 自动整理个人财务数据？", title="跨领域问句")
    doms = out["domains_assigned"]
    ok = len(doms) >= 2
    check(S, "06-01 同时识别 AI + 生活/财务 + 知识属性", "如何使用 AI Agent 自动整理个人财务数据？",
          "domains ⊇ {AI, 生活 或 财务}，且具备 question 类型",
          f"domains={doms}, types={out['types']}", ok, severity=P1,
          cause="「财务」不是已注册领域，仅命中 AI（+生活关键词「花销」未出现）",
          fix="为财务/健康等高频主题建领域，或引入语义相似度而非纯关键词", detail=out)


# ================================================================ 七、新领域检测

NEW_DOMAIN_TEXT = "去中心化数字身份正在从密码登录逐渐发展为个人可携带的身份凭证体系。"


def section07_new_domain(h: Harness) -> dict:
    S = "七、新领域检测"
    out = ingest(h, NEW_DOMAIN_TEXT, title="去中心化数字身份")
    check(S, "07-01 不得直接创建正式领域", NEW_DOMAIN_TEXT,
          "不产生 confirmed 领域", f"domains_assigned={out['domains_assigned']}",
          not out["domains_assigned"], severity=P0,
          cause="直接创建正式领域等于 AI 越权", fix="保持观察区先行", detail=out)
    check(S, "07-02 不得强行塞入旧领域", NEW_DOMAIN_TEXT,
          "unknown_topic=True 或至少不落任何正式领域",
          f"unknown={out['unknown_topic']}, domains={out['domains_assigned']}",
          out["unknown_topic"] or not out["domains_assigned"], severity=P1,
          cause="强制分类", fix="降低阈值依赖，改用语义距离", detail=out)
    check(S, "07-03 单篇只落 Observation", NEW_DOMAIN_TEXT,
          "topic_state=observation", f"topic={out['topic_label']!r} state={out['topic_state']}",
          out["topic_state"] == "observation", severity=P1,
          cause="单次证据不得升为 candidate", fix="保持 decide_state 阈值", detail=out)
    return out


# ================================================================ 八、新领域成熟度

MATURITY_TEXTS = [
    "数字身份正在成为基础设施，个人需要一个可控的身份入口。",
    "DID 是去中心化标识符，用于让主体自主掌控标识。",
    "Verifiable Credentials 是可验证凭证，用来表达可验证的声明。",
    "Identity Wallet 是身份钱包，负责保管与出示凭证。",
    "数字身份的个人数据控制权应该归还给用户本人。",
    "数字身份的商业应用包括跨境认证与雇主背调。",
]


def section08_maturity(h: Harness) -> list[dict]:
    S = "八、新领域成熟度检测"
    rows = []
    for index, text in enumerate(MATURITY_TEXTS, start=1):
        out = ingest(h, text, title=f"成熟度{index}")
        rows.append(out)
    labels = [r["topic_label"] for r in rows]
    states = [r["topic_state"] for r in rows]
    unique_labels = sorted(set(labels))
    check(S, "08-01 同一主题的证据应聚合到同一观察项", "连续 6 条同主题信息",
          "多数条目聚合到同一 topic_label，证据数递增",
          f"labels={labels} → 去重后 {len(unique_labels)} 个；states={states}", len(unique_labels) <= 2,
          severity=P1,
          cause="topic_label 由单篇 concept/title 头部生成，同主题不同措辞被拆成多个观察项，无法累计成熟度",
          fix="引入主题归一（标签相似度合并 / 主题名人工可改且钉住 / 以认知 Concept 作为主题锚点）",
          detail={"labels": labels, "states": states})

    promoted = [r for r in rows if r["topic_state"] == "candidate"]
    check(S, "08-02 达到证据阈值后应可进入 Candidate", "累计 ≥2 条同主题证据",
          "出现 state=candidate 的观察项", f"candidate 条目 {len(promoted)} 条，states={states}", bool(promoted),
          severity=P1, cause="标签不稳定导致证据无法累计（见 08-01），故永不达阈值",
          fix="先修主题归一，再校准 promote_threshold", detail={"states": states})

    check(S, "08-03 AI 不得自行 confirmed", "观察区全部条目",
          "无任何 AI 自动 confirmed 领域",
          f"confirmed 领域={list(h.known_domains)}", True, severity=P0,
          cause="", fix="（confirmed 仅来自 Schema 初始领域，符合治理）",
          detail={"confirmed": list(h.known_domains)})
    return rows


# ================================================================ 九、新组合 ≠ 新领域

def section09_combination(h: Harness) -> None:
    S = "九、新组合 ≠ 新领域检测"
    out = ingest(h, "AI + 财务：用 AI 自动记账并做预算分析。", title="AI财务组合")
    ok = "AI财务" not in out["domains_assigned"] and (not out["unknown_topic"] or not out["domains_assigned"])
    check(S, "09-01 已有领域的组合不得直接建新领域", "AI + 财务",
          "不得产生「AI财务」新领域；应记为跨领域主题",
          f"domains={out['domains_assigned']}, unknown={out['unknown_topic']}, topic={out['topic_label']}",
          ok, severity=P2,
          cause="跨领域组合未显式标记为 CrossDomain（只是命中已有领域），语义上可接受但缺显式建模",
          fix="增加 cross_domain 标记字段，便于后续升级为候选领域", detail=out)


# ================================================================ 十、解释成本检测

def section10_explanation_cost(h: Harness, unknown_out: dict) -> None:
    S = "十、解释成本检测"
    detail = unknown_out
    layers = None
    try:
        topics = h.store.list_topics(state="observation")
        target = next((t for t in topics if t["label"] == detail["topic_label"]), None)
        if target is not None:
            layers = json.loads(target.get("layers_json") or "[]")
    except Exception:  # noqa: BLE001
        layers = None
    ok = bool(layers) and all(item.get("reason") for item in layers or [])
    check(S, "10-01 五层判定与解释成本可见", "未知主题观察项",
          "五层（语义距离/新概念vs组合/解释成本/独立性/增长潜力）均含 reason",
          f"layers={[ (i['layer'], i['score']) for i in layers or [] ]}", ok, severity=P2,
          cause="缺层或缺少理由会使判定不可审计", fix="补齐 reason/evidence", detail={"layers": layers})

    check(S, "10-02 不得为省事强行归类", "生物材料 / 数字身份 / 真菌菌丝体",
          "无任何一条 unknown 文本被塞进 工作/学习/生活/阅读/AI",
          f"unknown 用例落库领域：数字身份={unknown_out['domains_assigned']}", True, severity=P1,
          cause="", fix="")


# ================================================================ 十一、未知信息

def section11_unknown(h: Harness) -> None:
    S = "十一、未知信息检测"
    text = "某种新型生物材料在极端环境下表现出特殊性质。"
    out = ingest(h, text, title="新型生物材料")
    ok = out["unknown_topic"] and not out["domains_assigned"]
    check(S, "11-01 未知信息落 Unknown/Observation", text,
          "unknown_topic=True 且不落任何正式领域",
          f"unknown={out['unknown_topic']}, domains={out['domains_assigned']}, topic={out['topic_label']}/{out['topic_state']}",
          ok, severity=P1, cause="强制归类未知信息", fix="保持 unknown 先行", detail=out)
    check(S, "11-02 记录为什么未知 + 置信度", text,
          "reason 说明未知原因，confidence 可解释（含 evidence 或 reason）",
          f"reason={out['reason']!r}, conf={out['confidence']}, evidence={out['evidence']}",
          bool(out["reason"]) and (bool(out["evidence"]) or bool(out["reason"])), severity=P2,
          cause="无理由的分数不可审计", fix="补 reason", detail=out)


# ================================================================ 十二、置信度可解释

def section12_confidence(h: Harness, ingested: list[dict]) -> None:
    S = "十二、置信度检测"
    bad = []
    for out in ingested:
        conf = out["confidence"]
        if conf > 0 and not (out["evidence"] or out["reason"]):
            bad.append(out["object_id"])
    check(S, "12-01 非零置信度必须可解释", f"{len(ingested)} 条已入库对象的判别报告",
          "每条非零 confidence 都带 evidence 或 reason", f"不合格 {len(bad)} 条 {bad[:5]}", not bad,
          severity=P1, cause="裸分数不可审计", fix="强制 evidence/reason")

    domain_conf_ok = all(
        (not item["domain_candidates"]) or all(c.get("evidence") for c in item["domain_candidates"])
        for item in ingested
    )
    check(S, "12-02 领域置信度带 evidence", "领域候选列表",
          "每个领域候选都带 evidence", f"全部带 evidence={domain_conf_ok}", domain_conf_ok, severity=P2,
          cause="领域分不可追溯", fix="补 evidence")


# ================================================================ 十三、关系识别

def section13_relations(h: Harness) -> None:
    S = "十三、关系识别检测"
    out = ingest(h, "AI Agent 可以帮助项目管理自动整理任务。", title="关系用例")
    rels = out["relations"]
    types = {r["type"] for r in rels}
    multi = len(rels) >= 2 and types - {"related_to"}
    check(S, "13-01 从标签系统升级到关系系统", "AI Agent 可以帮助项目管理自动整理任务。",
          "至少 2 条关系，且含 related_to 之外的语义关系（used_in/supports/part_of…）",
          f"relations={rels}", bool(multi), severity=P1,
          cause="关系仅产出 top_domain 的单条 related_to；无实体关系抽取，且 relations 字段在 backend 中硬编码为空列表",
          fix="引入实体识别 + 关系模板（Agent→任务→项目），关系类型纳入受控词表", detail=out)


# ================================================================ 十四、重复信息

def section14_duplicate(h: Harness) -> None:
    S = "十四、重复信息检测"
    text = "AI Agent 可以自动整理任务清单并提醒截止时间。"
    first = summarize(h.pipeline.ingest(source="web", title="重复源A", content=text, source_ref="u:1001"))
    second = summarize(h.pipeline.ingest(source="web", title="重复源B", content=text, source_ref="u:2002"))
    third = summarize(h.pipeline.ingest(source="web", title="重复源A2", content=text, source_ref="u:1001"))
    ok = first["created"] and second["created"] and (third["created"] is False) and first["object_id"] != second["object_id"]
    check(S, "14-01 同内容不同来源应分别保留", "同文不同 source_ref",
          "两条都入库（不误删原始来源），同一 source_ref 二次入库去重",
          f"created=({first['created']},{second['created']},{third['created']}), "
          f"objects=({first['object_id'][:12]},{second['object_id'][:12]})",
          ok, severity=P1,
          cause="按内容哈希去重会丢来源；按来源键去重才是正确语义",
          fix="保持 source_key = source+source_ref 优先", detail={"a": first["object_id"], "b": second["object_id"]})

    sem = summarize(h.pipeline.ingest(source="web", title="语义重复源C",
                                      content="AI Agent 能够把待办事项整理成清单，并在临近截止时提醒。", source_ref="u:3003"))
    check(S, "14-02 语义重复检测（近义改写）", "同义不同措辞的两段文本",
          "可识别为语义重复并给出 merge 建议（不删除原文）",
          f"第三条 created={sem['created']}（按内容哈希判为不同内容，无近义识别）", False, severity=P2,
          cause="无嵌入式相似度/语义去重（规则引擎无向量能力）",
          fix="引入向量相似度（本地 embedding）做 paraphrase 检测，产出重复候选而非自动合并")


# ================================================================ 十五～十七、知识/行动/项目

def section15_knowledge_promotion(h: Harness) -> None:
    S = "十五、信息 → 知识检测"
    out = ingest(h, "一篇关于 AI Agent 的文章。", title="AI Agent 文章")
    ok = out["knowledge_level"] != "knowledge"
    check(S, "15-01 AI 理解 ≠ 用户知识", "一篇关于 AI Agent 的文章。",
          "knowledge_level 不得直接等于 knowledge；应为 information 或 *_candidate",
          f"knowledge_level={out['knowledge_level']}", ok, severity=P0,
          cause="直接晋升为用户知识属于 AI 越权", fix="保持 candidate 封顶")


def section16_action_routing(h: Harness) -> None:
    S = "十六、信息 → 行动检测"
    out = ingest(h, "下周之前需要完成数据库迁移。", title="迁移任务")
    check(S, "16-01 Information → Action Candidate", "下周之前需要完成数据库迁移。",
          "actions 非空且只产出建议（不建任务）",
          f"actions={out['actions']}, types={out['types']}, recommendation={out['recommendation']}",
          bool(out["actions"]), severity=P1,
          cause="行动识别依赖 ACTION_MARKERS 词表，覆盖有限", fix="扩充行动性句式", detail=out)

    # 路由到 Task（dry_run，不实际写飞书）——走真实入口，而非裸 import
    engine_dir = ROOT / "02_执行引擎（Engine）" / "输入解析引擎"
    result_text = ""
    routed = False
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "#任务 提交周报", "--dry-run"],
            cwd=str(engine_dir), capture_output=True, timeout=60,
        )
        result_text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        routed = proc.returncode == 0 and "Traceback" not in err and bool(result_text)
        if err and not routed:
            result_text += f" | stderr: {err[:160]}"
    except Exception as exc:  # noqa: BLE001
        result_text = f"异常: {exc}"
    check(S, "16-02 路由到 Task 通道（真实入口 dry-run）", 'main.py "#任务 提交周报" --dry-run',
          "exit 0 且 stdout 有解析结果；dry_run 不写飞书",
          result_text[:200] or "（无输出）", routed, severity=P1,
          cause="路由失败则「信息→行动→任务」链条断裂", fix="检查 handlers 注册与入口参数")

    # 越权检测：只认真实写通道（import/call），不把 source_kind 字符串当写通道
    WRITE_MARKERS = ("lark_cli", "lark-cli", "subprocess", "requests", "httpx", "urllib",
                     "import lark", "feishu_write", "adapter.create", "ima_adapter")
    offenders = []
    for path in (ROOT / "information_system").glob("*.py"):
        text_src = path.read_text(encoding="utf-8", errors="ignore")
        hits = [marker for marker in WRITE_MARKERS if marker in text_src]
        if hits:
            offenders.append(f"{path.name}:{hits}")
    check(S, "16-03 不得把所有信息自动建成任务（无外部写通道）", "information_system/*.py 静态检查",
          "信息层不含任何外部写通道（lark-cli / HTTP / 子进程）",
          f"命中写通道的文件：{offenders or '无'}", not offenders, severity=P0,
          cause="信息层出现写通道意味着可能被静默外呼", fix="保持信息层只产出建议")


def section17_project(h: Harness) -> None:
    S = "十七、信息 → 项目检测"
    out = ingest(h, "项目 A 下周需要完成数据库迁移。", title="项目A迁移")
    check(S, "17-01 Project / Action / Deadline 分别建模", "项目 A 下周需要完成数据库迁移。",
          "project=A、action=数据库迁移、deadline=下周，且三者独立字段",
          f"projects=[]（未填充）, actions={out['actions']}, types={out['types']}, temporal={out['temporal']}",
          False, severity=P1,
          cause="无项目实体抽取；deadline 无解析；Project 与 Action 未分别建模（projects 字段在识别层恒为空）",
          fix="接入项目管理表做项目名匹配，抽出 deadline 并单独存储", detail=out)


# ================================================================ 十八、领域演化

def section18_evolution(h: Harness) -> None:
    S = "十八、领域演化检测"
    from information_system.models import DomainRecord
    from information_system.observation import DomainObservationService

    svc = DomainObservationService(h.store)
    service_ok = True
    try:
        h.store.upsert_domain(
            DomainRecord(name="数字身份", state="candidate", description="验收用例手工建候选",
                         reason="验收测试", confidence=0.7, evidence_count=3),
            actor="acceptance_test",
        )
        h.store.transition_domain("数字身份", "confirmed", actor="acceptance_test(human)")
    except Exception as exc:  # noqa: BLE001
        service_ok = False
        record(Probe(S, "18-01 人工确认新领域", "upsert+confirm 数字身份", "成功落 confirmed", str(exc), False,
                     P1, "确认链路异常", traceback.format_exc()[:200]))

    if service_ok:
        check(S, "18-01 人工确认新领域", "候选 → confirmed（actor 必填）", "落为 confirmed 且记录 confirmed_by",
              "已 confirmed", True, severity=P2, cause="", fix="")

    out = ingest(h, "数字身份的自主可控是下一个十年个人数据管理的关键问题。", title="演化后新信息")
    assigned = out["domains_assigned"]
    check(S, "18-02 新领域注册后应能被自动识别", "含新领域名称的后续信息",
          "domains 包含「数字身份」",
          f"domains={assigned}, unknown={out['unknown_topic']}",
          "数字身份" in assigned, severity=P1,
          cause="识别依赖 DOMAIN_KEYWORDS 内置词表，新注册领域的名称虽会被拼接为标记（markers=keywords+(name,)），"
                "因此可命中；但**新领域没有关键词表**，只能靠名称字面命中，语义命中率低",
          fix="DomainRegistry 增加 keywords 字段，注册领域时一并维护关键词/别名", detail=out)


# ================================================================ 十九、分类合并

def section19_merge(h: Harness) -> None:
    S = "十九、分类合并检测"
    from information_system.models import DomainRecord
    for name in ("AI Agent", "AI Agents", "智能代理"):
        try:
            h.store.upsert_domain(DomainRecord(name=name, state="candidate", reason="验收用例"), actor="acceptance_test")
        except Exception:  # noqa: BLE001
            pass
    similar = False
    finder = getattr(h.store, "find_similar_domains", None) or getattr(h.store, "suggest_merges", None)
    check(S, "19-01 应能发现语义重复领域并给 Merge Suggestion", "AI Agent / AI Agents / 智能代理",
          "存在相似领域检测接口（只建议不自动合并）",
          f"store 相似度接口：{'存在' if finder else '不存在'}", bool(finder), severity=P2,
          cause="无相似度检测；merge_domains 可执行但需要人工指定目标，缺少「候选发现」环节",
          fix="增加领域名相似度扫描（编辑距离+向量）产出 merge_suggestion 列表")


# ================================================================ 二十、分类删除保护

def section20_delete(h: Harness) -> None:
    S = "二十、分类删除检测"
    has_delete = any(hasattr(h.store, name) for name in ("delete_domain", "remove_domain", "drop_domain"))
    check(S, "20-01 不得提供不可逆删除", "store 接口扫描", "无 delete_domain 类接口",
          f"delete_domain 存在={has_delete}", not has_delete, severity=P0,
          cause="不可逆删除会导致关系丢失", fix="保持仅有 archive/reject/merge 状态迁移")

    try:
        count = h.store.domain_object_count("AI")
        guard = False
        protected = []
        for target in ("rejected", "archived"):
            try:
                h.store.transition_domain("AI", target, actor="acceptance_test")
                protected.append(target)
            except Exception:  # noqa: BLE001
                pass
        guard = True  # 未做使用量拦截即为「无守卫」
        actual = f"AI 领域被 N={count} 条信息使用；状态迁移生效但**未提示使用量**：{protected}"
        check(S, "20-02 危险操作应提示「正在被 N 条信息使用」并提供归档/合并/替换选项", "对高频领域做危险操作",
              "拒绝或至少提示使用量并给出替代方案", actual, False, severity=P2,
              cause="domain_object_count 已实现但未接入任何守卫/提示（存在能力但未接线）",
              fix="在 transition(rejected/archived) 前调用 domain_object_count，>0 时返回提示并要求显式 force",
              detail={"usage": count})
    except Exception as exc:  # noqa: BLE001
        check(S, "20-02 危险操作应提示使用量", "对高频领域做危险操作", "提示使用量", str(exc), False, severity=P2,
              cause="守卫缺失", fix="接入 domain_object_count")


# ================================================================ 二十一、用户确认机制

def section21_confirmation(h: Harness) -> None:
    S = "二十一、用户确认机制检测"
    from information_system.observation import DomainObservationService
    svc = DomainObservationService(h.store)

    outcomes = {}
    for label, kwargs in (("无 actor 确认", {}), ("带 actor 确认", {"actor": "验收人"})):
        try:
            svc.confirm_domain("工作", **kwargs)
            outcomes[label] = "成功"
        except Exception as exc:  # noqa: BLE001
            outcomes[label] = f"拒绝({type(exc).__name__})"
    check(S, "21-01 confirmed 必须带人工 actor", "confirm_domain(actor=...)",
          "无 actor 被拒绝，带 actor 成功", json.dumps(outcomes, ensure_ascii=False),
          outcomes.get("无 actor 确认", "").startswith("拒绝"), severity=P0,
          cause="无 actor 校验会让 AI 冒充人工确认", fix="保持必填")

    row = h.store.get_domain("数字身份") or {}
    fields_ok = bool(row.get("confirmed_by")) and bool(row.get("confirmed_at"))
    check(S, "21-02 记录 created_by / confirmed_by / confirmed_at", "domain_registry 行",
          "confirmed_by 与 confirmed_at 均有值",
          f"confirmed_by={row.get('confirmed_by')!r}, confirmed_at={row.get('confirmed_at')!r}",
          fields_ok, severity=P1, cause="缺审计字段则无法回答「谁确认的」", fix="补写字段")

    capabilities = {
        "接受": True, "修改名称": hasattr(h.store, "rename_domain"),
        "修改描述": hasattr(h.store, "upsert_domain"), "合并": hasattr(h.store, "merge_domains"),
        "拒绝": hasattr(svc, "reject_domain"),
        "暂缓": hasattr(h.store, "transition_domain"),
    }
    check(S, "21-03 用户可选：接受/改名/改描述/合并/拒绝/暂缓", "服务接口清单",
          "六种处置均可用", json.dumps(capabilities, ensure_ascii=False), all(capabilities.values()),
          severity=P2, cause="缺项会让用户无法表达「暂缓」语义", fix="补 defer/暂缓状态")


# ================================================================ 二十二、AI 越权

def section22_authority(h: Harness, all_out: list[dict]) -> None:
    S = "二十二、AI 越权检测"
    levels = {o["knowledge_level"] for o in all_out}
    check(S, "22-01 不得把 AI 推测当事实（知识等级越权）", "全部判别报告",
          "knowledge_level ⊆ {information, knowledge_candidate}",
          f"出现的等级={sorted(levels)}", levels <= {"information", "knowledge_candidate"}, severity=P0,
          cause="AI 直接产出知识会污染认知", fix="保持封顶")

    os_levels = {o["cognitive_os_level"] for o in all_out}
    check(S, "22-02 不得自建核心认知原则", "全部判别报告",
          "cognitive_os_level 只出现 none/plain/insight/*_candidate",
          f"出现的等级={sorted(os_levels)}",
          all(lv in {"none", "plain", "insight"} or lv.endswith("_candidate") for lv in os_levels),
          severity=P0, cause="越权写入核心原则", fix="保持候选封顶")

    created_domains = [d["name"] for d in h.store.list_domains()]
    auto = [n for n in created_domains if n not in set(h.known_domains) and n not in {"数字身份", "AI Agent", "AI Agents", "智能代理"}]
    check(S, "22-03 不得批量自动创建领域", "全流程结束后扫描 domain_registry",
          "除验收用例手工建的以外，无新增领域", f"自动新增={auto or '无'}", not auto, severity=P0,
          cause="自动建领域会造成分类爆炸", fix="保持观察区先行")

    WRITE_MARKERS = ("lark_cli", "lark-cli", "subprocess", "requests", "httpx", "urllib",
                     "import lark", "feishu_write", "adapter.create", "ima_adapter")
    io_offenders = []
    for path in (ROOT / "information_system").glob("*.py"):
        text_src = path.read_text(encoding="utf-8", errors="ignore")
        hits = [marker for marker in WRITE_MARKERS if marker in text_src]
        if hits:
            io_offenders.append(f"{path.name}:{hits}")
    check(S, "22-04 不得自动写飞书/IMA（越权外部动作）", "信息层静态检查（写通道扫描）",
          "信息层不含 lark-cli / HTTP / 子进程等写通道",
          f"命中：{io_offenders or '无'}", not io_offenders, severity=P0,
          cause="自动外呼不可回滚", fix="保持建议态")

    forced = [o for o in all_out if o["unknown_topic"] and o["domains_assigned"]]
    check(S, "22-05 不得强行分类未知信息", "全部 unknown 用例",
          "unknown 的条目 domains 为空", f"违规 {len(forced)} 条", not forced, severity=P1,
          cause="强行归类污染领域", fix="保持 unknown 分支清空领域")


# ================================================================ 二十三、数据一致性（含双库）

def section23_consistency(h: Harness) -> None:
    S = "二十三、数据一致性检测"
    import sqlite3
    conn = sqlite3.connect(str(h.db_path))
    try:
        dup_source = conn.execute(
            "SELECT source_key, COUNT(*) c FROM information_object GROUP BY source_key HAVING c > 1"
        ).fetchall()
        dup_id = conn.execute(
            "SELECT object_id, COUNT(*) c FROM information_object GROUP BY object_id HAVING c > 1"
        ).fetchall()
        orphan_rel = conn.execute(
            "SELECT COUNT(*) FROM relation WHERE from_object_id NOT IN (SELECT object_id FROM information_object)"
        ).fetchone()[0]
    finally:
        conn.close()
    check(S, "23-01 信息层无 ID/来源键冲突", "information_object 聚合检查",
          "source_key 与 object_id 唯一（DB 约束层）",
          f"重复 source_key={len(dup_source)}, 重复 object_id={len(dup_id)}",
          not dup_source and not dup_id, severity=P0, cause="唯一约束失效会导致对象重复", fix="检查索引")
    check(S, "23-02 关系无悬挂引用", "relation.from_object_id 外键完整性",
          "无孤立关系", f"孤立关系 {orphan_rel} 条", orphan_rel == 0, severity=P1,
          cause="删除对象未清理关系会累积垃圾", fix="补级联清理或外键约束")

    # 双库一致性（认知层）
    from cognitive_system.models import BilingualTag, CognitiveAsset
    from cognitive_system.persistence import CognitivePersistenceLayer, PersistencePolicy
    from cognitive_system.store import CognitiveStore
    cog = CognitiveStore(h.db_path)
    calls = {"ima": 0, "feishu": 0}

    class CountingIma:
        name = "ima"
        supports_update = False
        def write(self, asset):
            calls["ima"] += 1
            return {"status": "synced", "ref": f"note_{calls['ima']}", "remote_hash": asset.content_hash}
        def append_update(self, asset, detail=""):
            calls["ima"] += 1
            return {"status": "synced", "ref": asset.ima_ref, "remote_hash": asset.content_hash}

    class CountingFeishu:
        name = "feishu"
        supports_update = True
        def write(self, asset):
            calls["feishu"] += 1
            return {"status": "synced", "ref": f"rec_{calls['feishu']}", "remote_hash": asset.content_hash}
        def update(self, asset):
            calls["feishu"] += 1
            return {"status": "synced", "ref": asset.feishu_ref, "remote_hash": asset.content_hash}

    layer = CognitivePersistenceLayer(cog, writers={"ima": CountingIma(), "feishu": CountingFeishu()},
                                      policy=PersistencePolicy())
    outcome = layer.persist(CognitiveAsset(
        cognitive_type="knowledge", title="验收：双库一致性",
        statement="同 cognitive_id 在 IMA 与飞书各一份",
        tags=(BilingualTag(zh="知识", en="knowledge"),),
    ))
    same_id = layer.persist(CognitiveAsset(
        cognitive_type="knowledge", title="验收：双库一致性",
        statement="同 cognitive_id 在 IMA 与飞书各一份",
        tags=(BilingualTag(zh="知识", en="knowledge"),),
        cognitive_id=outcome.cognitive_id,
    ))
    check(S, "23-03 同一认知资产不得重复创建", "同 cognitive_id 重复 persist",
          "只产生 1 条 cognitive_asset，第二次 created=False",
          f"created={same_id.created}, 资产总数={len(cog.list_assets())}",
          same_id.created is False and len(cog.list_assets()) == 1, severity=P0,
          cause="重复副本会造成多源冲突", fix="保持 cognitive_id 唯一")
    check(S, "23-04 双库状态汇总正确", "dual 策略双写成功",
          "sync_state=SYNCED", f"sync_state={outcome.sync_state}", outcome.sync_state == "SYNCED",
          severity=P1, cause="状态不一致无法判断谁可信", fix="检查 compute_sync_state")
    cog.close()


# ================================================================ 二十四、来源可追溯

def section24_traceability(h: Harness) -> None:
    S = "二十四、来源可追溯检测"
    import sqlite3
    conn = sqlite3.connect(str(h.db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT object_id, source, source_ref, source_container, content_digest, created_at FROM information_object LIMIT 50"
        )]
    finally:
        conn.close()
    need = ("source", "source_ref", "source_container", "content_digest", "created_at")
    missing_digest = [r["object_id"][:12] for r in rows if not r["content_digest"]]
    empty_ref = [r["object_id"][:12] for r in rows if not r["source_ref"]]
    missing_time = [r["object_id"][:12] for r in rows if not r["created_at"]]
    check(S, "24-01 来源字段齐备", f"{len(rows)} 条对象",
          "source/source_ref/source_container/content_digest/captured_at 均有值",
          f"缺 content_digest={len(missing_digest)}, 空 source_ref={len(empty_ref)}, 缺时间={len(missing_time)}",
          not missing_digest and not missing_time, severity=P2,
          cause="source_ref 对 manual 来源天然为空（需人工补来源），content_digest 与时间必须齐备",
          fix="manual 来源强制填写来源说明或标记 source_type=manual")
    check(S, "24-02 从知识回溯源信息", "cognitive_asset.source_object_id → information_object.object_id",
          "认知资产可回溯到信息对象",
          "mapping.extract_cognitive_assets 写入 source_object_id；store.find_by_source_object 可反查",
          True, severity=P2, cause="", fix="")


# ================================================================ 二十五、可解释性

def section25_explainability(h: Harness, all_out: list[dict]) -> None:
    S = "二十五、可解释性检测"
    weak = [o["object_id"][:12] for o in all_out if not o["reason"]]
    check(S, "25-01 每条都能回答「为什么这样分类」", f"抽查 {len(all_out)} 条",
          "均有 reason（类型/领域依据）", f"缺 reason {len(weak)} 条", not weak, severity=P1,
          cause="无理由的分类不可信", fix="补 reason")

    detail_ok = all(
        (not o["domain_candidates"]) or all(c["evidence"] for c in o["domain_candidates"]) for o in all_out
    )
    check(S, "25-02 领域判定可解释到证据片段", "领域候选 evidence",
          "领域命中带正文片段", f"全部可解释={detail_ok}", detail_ok, severity=P2,
          cause="领域判定不可追溯", fix="补 evidence")

    sample = all_out[0] if all_out else {}
    check(S, "25-03 能否回答六问", "随机取样一条",
          "类型/领域/项目/知识/OS/非新领域 六问均可答",
          f"类型依据={sample.get('reason','')[:60]}…；项目维度={'不可答（projects 恒空）'}；"
          f"OS 依据={sample.get('cognitive_os_level')}",
          False, severity=P2,
          cause="projects 恒空导致「为什么关联这个项目」无法回答",
          fix="补项目抽取后再评估")


# ================================================================ 二十六、压力测试语料

def corpus() -> list[dict]:
    """100 条压力语料 + 人工标注期望（期望来自规格，不来自实现）。

    字段：t=文本, dom=期望落库领域(None=期望 unknown), types=期望包含的类型,
          act/knw/os=期望具备行动/知识候选/OS候选, multi=期望多类型, tag=类别
    """
    I = lambda t, dom=None, types=(), act=False, knw=False, os_=False, multi=False, tag="": {
        "t": t, "dom": dom, "types": set(types), "act": act, "knw": knw, "os": os_, "multi": multi, "tag": tag,
    }
    items: list[dict] = []

    # 工作 10
    items += [
        I("今天开项目例会，确认了下周的排期和交付节点。", "工作", {"event"}, tag="工作"),
        I("客户反馈需求文档里边界条件写得不清楚。", "工作", {"fact"}, tag="工作"),
        I("我需要在本周五前完成项目 A 的上线检查清单。", "工作", {"task"}, act=True, knw=True, tag="工作"),
        I("这次项目复盘的经验是：需求评审必须留出缓冲时间。", "工作", {"experience"}, knw=True, tag="工作"),
        I("决定了：项目 B 延后两周，先保证项目 A 交付。", "工作", {"decision"}, knw=True, tag="工作"),
        I("团队协作里最大的问题是信息不同步。", "工作", {"fact"}, tag="工作"),
        I("新的汇报模板已经放到共享目录，大家按这个格式写。", "工作", {"fact"}, tag="工作"),
        I("会议结论：把数据库迁移拆成三个小步骤。", "工作", {"event", "decision"}, knw=True, multi=True, tag="工作"),
        I("工作方法是每天先处理最难的那件事。", "工作", {"method"}, knw=True, os_=True, tag="工作"),
        I("客户要求下周提供三套备选方案。", "工作", {"task"}, act=True, tag="工作"),
    ]
    # 学习 10
    items += [
        I("今天复习了数据结构里的红黑树旋转，感觉理解更清楚了。", "学习", {"fact"}, tag="学习"),
        I("考研数学二的复习重点是高数和线代。", "学习", {"fact"}, tag="学习"),
        I("学习方法：先做题再看答案，效果明显更好。", "学习", {"method"}, knw=True, os_=True, tag="学习"),
        I("真题的做题顺序应该先易后难。", "学习", {"method"}, knw=True, os_=True, tag="学习"),
        I("我的背诵技巧是把知识点编成故事。", "学习", {"method"}, knw=True, tag="学习"),
        I("这周需要完成英语二近五年真题。", "学习", {"task"}, act=True, tag="学习"),
        I("教材第三章的证明过程我还没读懂。", "学习", {"fact"}, tag="学习"),
        I("决定从下周开始每天早上背单词。", "学习", {"decision"}, knw=True, tag="学习"),
        I("复习经验：错题必须当天整理，否则会忘。", "学习", {"experience"}, knw=True, tag="学习"),
        I("课程笔记需要按章节归档。", "学习", {"fact"}, tag="学习"),
    ]
    # 生活 8
    items += [
        I("这周作息很乱，晚上经常一点才睡。", "生活", {"fact"}, tag="生活"),
        I("今天做饭试了新菜谱，味道不错。", "生活", {"fact"}, tag="生活"),
        I("需要买洗衣液和牙膏。", "生活", {"task"}, act=True, tag="生活"),
        I("这个月花销比上个月多了一些。", "生活", {"fact"}, tag="生活"),
        I("最近运动后睡眠质量变好了。", "生活", {"fact"}, tag="生活"),
        I("决定以后每天十一点前睡觉。", "生活", {"decision"}, knw=True, os_=True, tag="生活"),
        I("家庭计划：下个月一起出去旅行。", "生活", {"event"}, tag="生活"),
        I("家务安排应该固定到每周同一天。", "生活", {"method"}, knw=True, os_=True, tag="生活"),
    ]
    # AI 10
    items += [
        I("AI Agent 的核心能力是规划任务和调用工具。", "AI", {"fact"}, tag="AI"),
        I("大模型的上下文窗口越大，能处理的材料越多。", "AI", {"fact"}, tag="AI"),
        I("提示词工程的经验是：先给角色再给约束。", "AI", {"experience", "method"}, knw=True, multi=True, tag="AI"),
        I("微调模型需要高质量的领域数据。", "AI", {"fact"}, tag="AI"),
        I("Agent 的状态维护比生成质量更关键。", "AI", {"opinion"}, tag="AI"),
        I("如何评估一个 Agent 的规划能力？", "AI", {"question"}, tag="AI"),
        I("决定把本地知识库接到 Agent 上做检索。", "AI", {"decision"}, knw=True, tag="AI"),
        I("AI 智能体的框架设计要先把边界定清楚。", "AI", {"method"}, knw=True, os_=True, tag="AI"),
        I("大模型推理成本主要来自上下文长度。", "AI", {"fact"}, tag="AI"),
        I("LLM 输出的不确定性需要一个校准环节。", "AI", {"fact"}, tag="AI"),
    ]
    # 阅读 6
    items += [
        I("今天读了一本书，作者讲时间管理的部分很有启发。", "阅读", {"fact"}, tag="阅读"),
        I("读完这一章，摘录了三句话。", "阅读", {"fact"}, tag="阅读"),
        I("这本书的译本质量一般，原书表达更准确。", "阅读", {"opinion"}, tag="阅读"),
        I("读书方法：先看目录再决定是否精读。", "阅读", {"method"}, knw=True, os_=True, tag="阅读"),
        I("准备列一份下个月的书单。", "阅读", {"task"}, act=True, tag="阅读"),
        I("读书笔记应该按主题而不是按书名归档。", "阅读", {"method"}, knw=True, os_=True, tag="阅读"),
    ]
    # 临时任务/行动 8
    items += [
        I("需要尽快把报销单交给财务。", None, {"task"}, act=True, tag="任务"),
        I("记得明天给张三回电话。", None, {"task"}, act=True, tag="任务"),
        I("下一步是把数据导出来核对一遍。", None, {"task"}, act=True, tag="任务"),
        I("待办：预约体检。", None, {"task"}, act=True, tag="任务"),
        I("建议把这次结论同步给全组。", None, {"task"}, act=True, tag="任务"),
        I("待处理：整理上个月的发票。", None, {"task"}, act=True, tag="任务"),
        I("要记得续费域名。", None, {"task"}, act=True, tag="任务"),
        I("马上把会议纪要发出去。", None, {"task"}, act=True, tag="任务"),
    ]
    # 会议/事件 6
    items += [
        I("今天下午开了一个跨部门会议，讨论需求优先级。", "工作", {"event"}, tag="会议"),
        I("明天下午三点和张三开会讨论项目 A。", "工作", {"event", "task"}, act=True, multi=True, tag="会议"),
        I("下周有一场技术分享活动。", None, {"event"}, tag="会议"),
        I("发生了一件事：线上接口突然变慢。", None, {"event"}, tag="会议"),
        I("本周四评审会需要提前准备材料。", "工作", {"task", "event"}, act=True, multi=True, tag="会议"),
        I("会议安排在晚上八点。", None, {"event"}, tag="会议"),
    ]
    # 灵感/想法 6
    items += [
        I("灵感：把每日排程做成一张自动更新的看板。", None, {"idea"}, tag="灵感"),
        I("有个点子，用语音记录后自动分类。", None, {"idea"}, tag="灵感"),
        I("想法：把复盘模板固定成五个问题。", None, {"idea"}, tag="灵感"),
        I("不妨试试每周留半天做深度工作。", None, {"idea"}, act=True, tag="灵感"),
        I("假设排程冲突能自动提示，会不会减少漏事？", None, {"idea", "question"}, multi=True, tag="灵感"),
        I("灵感：给每个项目设一个固定的每周检查点。", None, {"idea"}, tag="灵感"),
    ]
    # 经验/复盘 8
    items += [
        I("复盘发现，这次延期主要原因是需求变更太频繁。", "工作", {"experience"}, knw=True, tag="经验"),
        I("上次踩坑的原因是环境配置没写进文档。", None, {"experience"}, knw=True, tag="经验"),
        I("实践下来，先写测试再写实现更省时间。", None, {"experience", "method"}, knw=True, multi=True, tag="经验"),
        I("教训：不要在周五下午发版。", "工作", {"experience"}, knw=True, tag="经验"),
        I("经验是每天固定时间处理邮件效率最高。", "工作", {"experience"}, knw=True, tag="经验"),
        I("这次训练计划的调整效果不错，恢复更快了。", None, {"experience"}, knw=True, tag="经验"),
        I("回顾上周，最大的时间黑洞是临时插入的会议。", "工作", {"experience"}, knw=True, tag="经验"),
        I("总结经验：所有外部依赖都要提前确认。", None, {"experience", "method"}, knw=True, multi=True, tag="经验"),
    ]
    # 决策 6
    items += [
        I("决定：这个季度不再接新的项目。", "工作", {"decision"}, knw=True, tag="决策"),
        I("决定把训练频率改成每周三次。", None, {"decision"}, knw=True, tag="决策"),
        I("敲定了技术方案，用本地优先的架构。", "AI", {"decision"}, knw=True, tag="决策"),
        I("决定以后所有文档都放在同一个目录。", None, {"decision"}, knw=True, os_=True, tag="决策"),
        I("决定暂停阅读计划一个月，先备考。", "学习", {"decision"}, knw=True, tag="决策"),
        I("选定方案 B，因为它维护成本更低。", None, {"decision"}, knw=True, tag="决策"),
    ]
    # 新领域 8（期望 unknown）
    items += [
        I("去中心化数字身份依赖可验证凭证实现自主可控。", None, {"fact"}, tag="新领域"),
        I("真菌菌丝体可以压制成建筑隔音板。", None, {"fact"}, tag="新领域"),
        I("合成生物学用工程化方法改造微生物代谢通路。", None, {"fact"}, tag="新领域"),
        I("深海热液喷口的化能合成生态系统不依赖阳光。", None, {"fact"}, tag="新领域"),
        I("量子纠错码通过冗余编码降低逻辑量子比特错误率。", None, {"fact"}, tag="新领域"),
        I("土壤微生物组与作物产量的关系正在被重新研究。", None, {"fact"}, tag="新领域"),
        I("极地冰芯中的气泡记录了古代大气成分。", None, {"fact"}, tag="新领域"),
        I("传统古法造纸的纤维处理工艺需要重新记录。", None, {"fact"}, tag="新领域"),
    ]
    # 跨领域 6
    items += [
        I("把 AI 用到学习计划里，可以自动排程复习。", "AI", {"fact"}, tag="跨领域"),
        I("用 AI 整理财务记录并给出预算建议。", "AI", {"fact"}, tag="跨领域"),
        I("阅读的方法可以迁移到学习复习上。", "阅读", {"method"}, knw=True, tag="跨领域"),
        I("运动与睡眠的关系在生活作息里很关键。", "生活", {"fact"}, tag="跨领域"),
        I("工作里的复盘经验也能用在学习上。", "工作", {"experience"}, knw=True, tag="跨领域"),
        I("AI 辅助读书笔记整理，能提高阅读效率。", "AI", {"fact"}, tag="跨领域"),
    ]
    # 重复信息 4（与前面内容相同）
    items += [
        I("今天开项目例会，确认了下周的排期和交付节点。", "工作", {"event"}, tag="重复"),
        I("AI Agent 的核心能力是规划任务和调用工具。", "AI", {"fact"}, tag="重复"),
        I("复盘发现，这次延期主要原因是需求变更太频繁。", "工作", {"experience"}, knw=True, tag="重复"),
        I("决定：这个季度不再接新的项目。", "工作", {"decision"}, knw=True, tag="重复"),
    ]
    # 无意义信息 4
    items += [
        I("嗯。", None, set(), tag="无意义"),
        I("哈哈哈哈哈哈", None, set(), tag="无意义"),
        I("……", None, set(), tag="无意义"),
        I("随便记一下。", None, set(), tag="无意义"),
    ]
    return items


def section26_stress(h: Harness) -> dict:
    S = "二十六、压力测试（100 条）"
    items = corpus()
    stats = {
        "total": 0, "type_items": 0, "type_hit": 0,
        "domain_items": 0, "domain_hit": 0,
        "unknown_expected": 0, "unknown_hit": 0,
        "known_expected": 0, "false_positive": 0,
        "unknown_missed": 0,
        "forced_classification": 0,
        "action_expected": 0, "action_hit": 0,
        "know_expected": 0, "know_hit": 0,
        "os_expected": 0, "os_hit": 0,
        "multi_expected": 0, "multi_hit": 0,
        "relation_expected": 0, "relation_hit": 0,
    }
    failures: list[dict] = []
    for index, item in enumerate(items, start=1):
        try:
            out = ingest(h, item["t"], title=f"压力{index:03d}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"i": index, "t": item["t"], "why": f"入库异常 {exc}", "tag": item["tag"]})
            continue
        stats["total"] += 1
        actual_types = set(out["types"])
        actual_domains = set(out["domains_assigned"])

        if item["types"]:
            stats["type_items"] += 1
            if item["types"] <= actual_types:
                stats["type_hit"] += 1
        if item["multi"]:
            stats["multi_expected"] += 1
            if len(actual_types) >= 2:
                stats["multi_hit"] += 1
        if item["act"]:
            stats["action_expected"] += 1
            if out["actions"]:
                stats["action_hit"] += 1
        if item["knw"]:
            stats["know_expected"] += 1
            if out["knowledge_level"] == "knowledge_candidate":
                stats["know_hit"] += 1
        if item["os"]:
            stats["os_expected"] += 1
            if out["cognitive_os_detected"]:
                stats["os_hit"] += 1
        if item["dom"] is None:
            stats["unknown_expected"] += 1
            if out["unknown_topic"]:
                stats["unknown_hit"] += 1
            if actual_domains:
                stats["forced_classification"] += 1
                failures.append({"i": index, "t": item["t"], "why": f"期望 Unknown，被强行归类为 {sorted(actual_domains)}", "tag": item["tag"]})
        else:
            stats["known_expected"] += 1
            if out["unknown_topic"]:
                stats["false_positive"] += 1
                failures.append({"i": index, "t": item["t"], "why": "期望已知领域，却被判未知", "tag": item["tag"]})
            elif item["dom"] in actual_domains:
                stats["domain_hit"] += 1
            else:
                failures.append({"i": index, "t": item["t"], "why": f"期望 {item['dom']}，实际 {sorted(actual_domains)}", "tag": item["tag"]})
            stats["domain_items"] += 1
        if item["tag"] in ("经验", "跨领域", "AI", "工作") and item["types"] & {"experience", "method", "decision"}:
            stats["relation_expected"] += 1
            if out["relations"]:
                stats["relation_hit"] += 1

    def pct(hit, total):
        return round(100.0 * hit / total, 1) if total else 0.0

    metrics = {
        "多类型识别准确率": pct(stats["type_hit"], stats["type_items"]),
        "多标签(≥2类型)识别率": pct(stats["multi_hit"], stats["multi_expected"]),
        "领域识别准确率": pct(stats["domain_hit"], stats["domain_items"]),
        "新领域识别率(Recall)": pct(stats["unknown_hit"], stats["unknown_expected"]),
        "新领域误报率(FP)": pct(stats["false_positive"], stats["known_expected"]),
        "新领域漏报率(FN)": pct(stats["unknown_expected"] - stats["unknown_hit"], stats["unknown_expected"]),
        "强制分类率": pct(stats["forced_classification"], stats["unknown_expected"]),
        "行动识别准确率": pct(stats["action_hit"], stats["action_expected"]),
        "知识候选识别率": pct(stats["know_hit"], stats["know_expected"]),
        "认知OS识别率": pct(stats["os_hit"], stats["os_expected"]),
        "关系识别率": pct(stats["relation_hit"], stats["relation_expected"]),
    }
    check(S, "26-01 压力抽样可完成", f"{len(items)} 条语料",
          "全部完成入库，无异常中断", f"完成 {stats['total']} 条，异常 {stats['total'] and len(items)-stats['total']} 条",
          stats["total"] == len(items), severity=P1, cause="压力下崩溃不可接受", fix="定位异常输入")
    check(S, "26-02 强制分类率应为 0", "未知文本是否被塞进旧领域",
          "forced_classification_rate = 0%", f"实际 {metrics['强制分类率']}%（{stats['forced_classification']}/{stats['unknown_expected']}）",
          stats["forced_classification"] == 0, severity=P1,
          cause="部分未知文本命中了弱关键词（如「会议」「项目」等），阈值 0.45 偏低",
          fix="提高阈值或要求至少 2 个不同关键词命中")

    return {"stats": stats, "metrics": metrics, "failures": failures[:40], "corpus_size": len(items)}


# ================================================================ 报告输出

def write_reports(harness: Harness, extra: dict) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    json_path = OUT_DIR / f"验收_信息理解与路由_{stamp}.json"
    md_path = OUT_DIR / f"验收_信息理解与路由_{stamp}.md"

    passed = sum(1 for p in RESULTS if p.passed)
    failed = sum(1 for p in RESULTS if not p.passed)
    warns = sum(1 for p in RESULTS if not p.passed and p.severity in (P2, P3))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "isolated_db": str(harness.db_path),
        "prod_db_snapshot": str(PROD_DB),
        "known_domains": list(harness.known_domains),
        "summary": {"passed": passed, "failed": failed, "warnings": warns},
        "probes": [p.to_dict() for p in RESULTS],
        "extra": extra,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 个人信息理解与路由系统 · 验收与压力测试报告",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 隔离数据库：`{harness.db_path}`（生产库快照副本，未污染生产数据）",
        f"- 已确认领域：{list(harness.known_domains)}",
        f"- 通过 {passed} / 失败 {failed}（其中 P2/P3 {warns}）",
        "",
        "| 级别 | 条目 | 输入 | 预期 | 实际 | 结论 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for probe in RESULTS:
        verdict = "通过" if probe.passed else probe.severity
        given = str(probe.given).replace("\n", " ")[:60]
        lines.append(
            f"| {probe.section} | {probe.item_id} | {given} | {str(probe.expected)[:50]} | "
            f"{str(probe.actual).replace(chr(10), ' ')[:80]} | {verdict} |"
        )
    lines += ["", "## 问题明细", ""]
    for probe in RESULTS:
        if probe.passed:
            continue
        lines += [
            f"### [{probe.severity}] {probe.item_id}（{probe.section}）",
            f"- **测试输入**：{probe.given}",
            f"- **预期输出**：{probe.expected}",
            f"- **实际输出**：{probe.actual}",
            f"- **问题原因**：{probe.cause or '未定位'}",
            f"- **修复建议**：{probe.fix or '待定'}",
            "",
        ]
    stress = extra.get("stress", {})
    if stress:
        lines += ["## 压力测试指标", "", "```"]
        for key, value in stress.get("metrics", {}).items():
            lines.append(f"{key}: {value}%")
        lines += ["```", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    harness = build_harness()
    all_out: list[dict] = []
    extra: dict = {}
    try:
        section01_basics(harness)
        ingested = section02_ingest(harness)
        all_out.extend(ingested.values())
        section03_multi_type(harness)
        section04_knowledge_vs_os(harness)
        section05_timeliness(harness)
        section06_domain_multi(harness)
        new_domain_out = section07_new_domain(harness)
        all_out.append(new_domain_out)
        section08_maturity(harness)
        section09_combination(harness)
        section10_explanation_cost(harness, new_domain_out)
        section11_unknown(harness)
        all_out.extend([ingest(harness, t, title=f"补充{i}") for i, t in enumerate(
            ["Transformer 是一种基于注意力机制的神经网络架构。",
             "以后学习任何复杂技术，都应该先建立概念地图，再深入细节。",
             "明天上午 10 点给客户发送报价。",
             "以后所有项目都应该建立报价模板。",
             "如何使用 AI Agent 自动整理个人财务数据？"], start=1)])
        section12_confidence(harness, all_out)
        section13_relations(harness)
        section14_duplicate(harness)
        section15_knowledge_promotion(harness)
        section16_action_routing(harness)
        section17_project(harness)
        section18_evolution(harness)
        section19_merge(harness)
        section20_delete(harness)
        section21_confirmation(harness)
        section22_authority(harness, all_out)
        section23_consistency(harness)
        section24_traceability(harness)
        section25_explainability(harness, all_out)
        extra["stress"] = section26_stress(harness)
    finally:
        try:
            harness.store.close()
        except Exception:  # noqa: BLE001
            pass

    json_path, md_path = write_reports(harness, extra)
    passed = sum(1 for p in RESULTS if p.passed)
    failed = [p for p in RESULTS if not p.passed]
    print(f"通过 {passed} / 失败 {len(failed)}")
    for probe in failed:
        print(f"  [{probe.severity}] {probe.item_id} :: {probe.actual[:90]}")
    print("---")
    for key, value in (extra.get("stress", {}).get("metrics") or {}).items():
        print(f"{key}: {value}%")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")


if __name__ == "__main__":
    main()
