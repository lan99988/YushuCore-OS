# 个人混合管理系统 — 系统蓝图（Project Mental Model）

> 最后更新：2026-09-27
> 定位：**项目认知层**总入口。配套文档见同目录 `ARCHITECTURE.md`（架构）、`DATA_MODEL.md`（数据模型）、`SKILL_INDEX.md`（技能索引）、`WORKFLOW.md`（运行流程）、`DECISION_LOG.md`（决策记录）。
> 飞书连接配置：只从本地集成配置读取；本文不保存 Token。

---

## 一、一句话定位

**以前端六条用户逻辑链组织体验、以联邦式事实源承载数据、由 Agent 协助规划与执行的个人 AI 管理操作系统**——主攻考研（数二/英二/政/408）+ 日常项目，并扩展出身体管理（Body OS）子系统。

---

## 二、项目卡片

| 项 | 内容 |
|------|------|
| **项目目标** | 用"输入即完成"的低摩擦方式，把任务/灵感/Bug/习惯/深度工作/比赛/财务/社交/创作/知识/身体 统一进一个可排程、可复盘、可多 Agent 协作的系统 |
| **解决什么问题** | 个人数据散落（微信/备忘录/Excel/脑子）、状态不透明、排程靠手算、多 AI 协作无共同事实源 |
| **目标用户** | 系统主人（"我自己"，深圳，考研 + 日常项目）+ 协作 Agent（WorkBuddy / 随手录 / 其他 Agent） |
| **核心功能** | ① 前缀指令快速录入 ② 每日 7:00 排程推送 ③ 深度工作/习惯追踪 ④ 比赛/财务/社交/创作/知识管理 ⑤ 每周复盘 ⑥ 身体管理（Garmin 精力 + 训练/营养/恢复）⑦ 多 Agent 共享状态 |
| **技术栈** | Python 3.13（引擎/脚本）· 飞书 Base + lark-cli（执行态与移动触达）· WorkBuddy（输入口与 Agent 运行时）· JSON Schema（数据模型）· SQLite（信息投影与 analytics）· Node（lark-cli 运行时） |
| **项目规模** | 顶层 10 目录 + `runtime`；15 个工程内 Skill（yushu_00~14）+ 2 个 user-level；18 个飞书数据资产（含 3 个待建表）；引擎层 ~51 个 `.py`；测试 ~20 个模块 |
| **当前状态** | 核心架构完成并稳定运行；输入解析引擎 v1.2 已完成"搬家不装修"拆分（Router + 17 handlers，旧 2395 行冻结为 `input_parser_old.py`）；Body OS 阶段一（Garmin 精力契约）已落地；知识库已迁移至外部 `D:\Knowledge`（`knowledge_base.mode: external_read_only`），不再随仓库维护 |
| **未来规划** | ① 训练/营养/身体指标三表正式落库 ② Phase 5 Service/format_output 治理（切断 `_call_standard` 旧桥）③ 外部知识库真正可用 ④ 排程引擎 `calendar_sync.py` 独立 runtime 治理 ⑤ 项目知识库长期化（本认知层即第一步） |

---

## 三、核心模块速览

```
输入层      前缀指令(#任务/#习惯/#身体…) → 随手录/WorkBuddy 自然语言
   ↓
Skill 层    15 个 yushu_* Skill（路由/解析/处理器/身体域）    ← 01_Skill能力库
   ↓
Engine 层   main.py → router.dispatch() → 17 handlers         ← 02_执行引擎
   ↓
Data 层     飞书 / Knowledge / SQLite / Garmin               ← 联邦式事实源
   ↓
Feishu 层   飞书 Base / IM 推送 / 日历 / 任务                  ← 06_外部连接
```

---

## 四、关键入口索引（先读这些）

| 你想了解 | 读 |
|---------|-----|
| 系统怎么搭起来、谁调谁 | `ARCHITECTURE.md` |
| 18 张表 + 字段定义来源 + BodyOS 数据契约 | `DATA_MODEL.md` |
| 15 个 Skill 各自管什么、怎么触发 | `SKILL_INDEX.md` |
| 一条指令从输入到落库的过程、每日推送怎么来 | `WORKFLOW.md` |
| 为什么这么设计、踩过哪些坑、红线是什么 | `DECISION_LOG.md` |
| 新 Agent 入职（身份/纪律/lark-cli 速查） | `NEW_AGENT_ONBOARDING.md` |
| 全部表字段清单（旧但详） | 本文件"历史版本"段 / `yushu_00_系统注册表/SKILL.md` |

> 注：本文件取代 2026-07-01 旧版蓝图。旧版未涵盖 v1.2 输入解析拆分与 Body OS，已作废。

---

## 五、命名与红线（必须遵守）

- **目录**：`编号_中文名称（英文标识）`，中文主、英文辅，两位数字固定排序（00 最上，09 最下）。
- **Skill**：扁平一级，放在 `01_Skill能力库（Skills）/`，`yushu_` 前缀命名空间。真实落点经 junction 暴露给框架 `.workbuddy/skills/`。
- **引擎跨目录 import**：靠各引擎头部的 `_ensure_*_path()` 把兄弟引擎目录注册进 `sys.path`，不依赖旧 `input_parser_old` 初始化。
- **Git 陷阱**：根 `.lark-cli/`、`.workbuddy/` 均为 junction；`.gitignore` 必须覆盖 `lark-cli/`、`node_modules/`、`09_临时文件（Temp）/`、`运行状态（Runtime）/`，避免提交密钥/依赖/状态。

---

## 六、2026-09-26 下一阶段架构

系统后续按 ADR-010 演进：

- 旧“飞书唯一事实源”表述仅作为历史记录；当前规则是按数据性质划分权威来源。
- 前端统一为 Capture、Plan、Today、Adjust、Review、Explore 六条用户逻辑链。
- 中间层由 Cognitive Core 和 Orchestration Layer 统一做上下文、能力规划、权限与审计。
- 后端能力通过 Capability Plugin 注册和调用；Skill 只保留“何时及如何使用能力”的说明职责。
- 数据采用联邦式事实源：飞书负责执行态，D:\Knowledge 负责知识正文，information_system 负责信息投影，Garmin 数据集负责身体原始数据。
- 迁移采用 Strangler Migration，新路径稳定前保留 input_parser、daily_scheduler 和现有 handlers。

详细边界见 PROJECT_CHARTER.md、ARCHITECTURE_V2.md、PLUGIN_STANDARD.md、AUTONOMY_POLICY.md 和 DOMAIN_REGISTRY.md。

### Yushu Adaptive OS v1.0 验收状态

本轮已经形成可离线验证的六条前端逻辑链：Capture / Plan / Today / Adjust / Review / Explore。用户入口不要求理解后台插件；能力由 Registry、Planner、Runtime Policy 和 Executor 解析与执行。

当前冻结的系统不变量：

- 默认 `network_mode` 为 `OFF`，Agent 自治等级不超过 2；
- 外部消息、固定会议变更、支付、投资、不可逆删除与外部承诺必须审批；
- 事件和审计只保存受控元数据，不保存凭证或业务正文；
- Finance 只生成月度聚合快照提案，Social 以互动事件和承诺为中心；
- dormant 领域只在真实请求出现时激活；
- Personal Rule 需要多来源证据与授权审核，撤销后立即停止参与建议；
- 新路径通过 Strangler Migration 共存，旧入口尚未达到删除条件。

版本验证入口为 `scripts/final_acceptance.py`；插件清单、六 Flow 冒烟、全量门禁和恢复步骤分别见 `PLUGIN_INVENTORY.md`、`RUNBOOK.md` 与 `scripts/verify.py`。

---

## 七、三阶段喂养法（给未来接手 AI 的顺序）

1. **建立世界观**：读 README.md → 本蓝图 → ARCHITECTURE.md → 目录树。
2. **建立内部结构**：读 `main.py` + `router.py`（入口）、`DATA_MODEL.md`（数据模型）、`SKILL_INDEX.md`（模块职责）。
3. **深入执行**：读具体 handler / 某张表 Schema / 某条 Bug，再动手改。

**绝不要一上来读全部代码**——本项目 80% 行为由 `main.py → router → 17 handlers` + 飞书 Base 决定。
