# 系统架构（ARCHITECTURE）

> 配套：`SYSTEM_BLUEPRINT.md` · `DATA_MODEL.md` · `SKILL_INDEX.md` · `WORKFLOW.md` · `DECISION_LOG.md`
> 最后更新：2026-08-03。本文是"系统空间感"层——谁调用谁、数据怎么流动、哪些是核心节点。

---

## 一、分层架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      用户输入（自然人 + Agent）                │
│   微信 / WorkBuddy 对话框  →  "#任务 ..." 或自然语言           │
└───────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  SKILL 层  (01_Skill能力库，yushu_* 扁平一级)                  │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐    │
│  │ 01 输入解析 │  │ 02 意图分类 │  │ 03 快速查询            │    │
│  │ Router     │  │ Router     │  │ Router                │    │
│  └─────┬──────┘  └─────┬──────┘  └───────────┬──────────┘    │
│  ┌─────┴──────────────┴──────────────────────┴──────────┐   │
│  │ 04 飞书操作 Processor（唯一写入口）                       │   │
│  │ 05 问答校准 / 06 每日排程 / 10~14 身体域 Skill           │   │
│  └───────────────────────────┬──────────────────────────┘   │
└───────────────────────────────┼─────────────────────────────┘
                                 │ 委托
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  ENGINE 层  (02_执行引擎，纯后台 Python，不可见)              │
│                                                               │
│  输入解析引擎/                                                │
│     main.py ──▶ router.dispatch() ──▶ handlers/ (17+)        │
│        │            │  ROUTES 表（前缀→handler）             │
│        │            └─ _call_standard（旧桥，Phase5 治理）   │
│        └─ input_parser_old.py  (Frozen Behavior Reference)  │
│  每日排程引擎/  daily_scheduler.py + calendar_sync.py        │
│  数据分析引擎/  analytics_engine.py  (SQLite)                │
│  复盘分析引擎/  weekly_deep_review.py                        │
└───────────────────────────────┬─────────────────────────────┘
                                 │ 读写
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  DATA 层  (04_数据中心)                                       │
│  数据模型（Schema）/  运行状态（Runtime）/  系统配置（Config） │
│  ★ 飞书 Base = 唯一事实源（不维护本地主库）                    │
└───────────────────────────────┬─────────────────────────────┘
                                 │ lark-cli（直调 Node）
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  FEISHU 层  (06_外部连接/飞书，lark-cli 软链)                 │
│   多维表格 Base · IM 推送 · 日历事件 · 飞书任务                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、核心调用链（一次 `#` 指令）

```
main.py (CLI 解析)
   → router.dispatch(raw_text)
        → _resolve_route_key()        # 读 ROUTES 表 + legacy.detect_prefix
        → ROUTE_HANDLERS[route_key]   # 17 个 handler 之一
             → handlers/xxx.py        # 业务计算 + 变量提取
             → yushu_04 飞书操作 Processor（唯一写入口）
                  → lark-cli base +record-upsert → 飞书 Base
        → _format_output(result) → print
```

**入口文件职责（方法四：找到"心脏"）**

| 文件 | 职责 | 不要动 |
|------|------|--------|
| `02_执行引擎/输入解析引擎/main.py` | 正式入口：CLI 参数解析 → `dispatch` | 仅做参数解析，不含业务 |
| `02_执行引擎/输入解析引擎/router.py` | 路由层：`ROUTES` + `ROUTE_HANDLERS` + `dispatch` | 分发逻辑，不搬业务 |
| `02_执行引擎/输入解析引擎/input_parser.py` | **Shim**（12 行）：`from main import main` | 仅兼容旧调用链 |
| `02_执行引擎/输入解析引擎/input_parser_old.py` | **冻结旧行为基准**（2395 行，md5 `a60437b6cfdd4eb8a0bf226865d751ef`） | 禁止修改，仅作委托源 |
| `02_执行引擎/输入解析引擎/handlers/*.py` | 17+ 业务 handler（已迁移并冻结） | 单测基线 194/194 |

> 当前测试基线：194/194 PASS；Golden 7 PASS + 3 SKIP；`input_parser_old.py` md5 不变。

---

## 三、模块职责表（方法五）

| 模块 | 层 | 职责 | 输入 | 输出 |
|------|----|------|------|------|
| main.py | Engine | 程序启动、CLI 解析 | 命令行文本 | 调 dispatch |
| router | Engine | 前缀→handler 分发 | raw_text | 格式化结果 |
| handlers/* | Engine | 17 类业务（任务/灵感/Bug/精力/习惯/深度/比赛/身体…） | raw_text | 解析结果 dict |
| daily_scheduler | Engine | 每日排程 + 模块提醒生成 | 全部业务表 | 飞书推送文本 + 日历事件 |
| calendar_sync | Engine | 排程写入飞书日历、冲突检测 | 排程结果 | 日历事件 + `_calendar_log.json` |
| analytics_engine | Engine | 统计/趋势 | Runtime SQLite | 报表 |
| weekly_deep_review | Engine | 周报可视化 | 深度/习惯数据 | ASCII 周报 |
| yushu_00 注册中心 | Skill | Base Token/表ID/lark-cli 模板（只读"有什么"） | — | 元数据 |
| yushu_04 飞书操作 | Skill | **唯一写入口** | 各 handler | 飞书记录 |

---

## 四、数据流（方法六：静态 + 动态）

**静态拓扑**：`用户输入 → Skill → Schema(定义) → Repository(未来) → 飞书 Base(存储)`。

**动态——录入流**：
```
#任务 做数学真题 【项目：数学二】【精力：高】
  → handlers/standard_record
  → 提取变量(title/project/energy/...)
  → build_record → 飞书执行库(tblNQCB4pn6Rso4a)
```

**动态——每日推送流**：
```
每日 07:00 automation
  → daily_scheduler.py 读 18 表
  → 排程算法(权重分/时段/精力)
  → calendar_sync.py 写飞书日历
  → im +messages-send 推送给主人
```

**动态——多 Agent 同步流**：
```
Agent A ──读写──▶ 飞书 Base（唯一状态中枢）◀──读写── Agent B
                  ↑ 状态 + 责任人 + 状态更新时间 三字段作同步信号
                  └ daily_scheduler 每日状态广播
```

---

## 五、跨目录机制（为什么能 import 通）

引擎分散在 `02_执行引擎` 各子目录，彼此 import 靠**各引擎头部的 `_ensure_*_path()`** 把 `02_执行引擎（Engine）` 父目录注册进 `sys.path`。运行方式：

```bash
python "02_执行引擎（Engine）/输入解析引擎/main.py" "#复盘 7"
python "02_执行引擎（Engine）/每日排程引擎/daily_scheduler.py" --analytics
```

> ⚠️ `runtime/` 与 `04_数据中心/运行状态（Runtime）` 是同一目录的 junction；handler 写共享 runtime 必须上溯到引擎根，**禁止落到 `handlers/runtime/`**（`calendar_sync.py` 仍用独立 runtime，是已知 issue，Phase 5 治理）。
