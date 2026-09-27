# 决策记录（DECISION_LOG）

> 配套：`SYSTEM_BLUEPRINT.md` · `ARCHITECTURE.md` · `DATA_MODEL.md` · `SKILL_INDEX.md` · `WORKFLOW.md`
> 最后更新：2026-08-03。本文是"为什么这么设计"层——关键架构决策、红线、已知坑、固化约定。

---

## 一、关键架构决策

### D1 — junction 桥接框架硬编码路径（2026-07-23 固化）
- **决策**：真实文件按中文命名体系存放；框架硬编码路径（`.workbuddy/skills`、`.workbuddy/memory`、`.workbuddy/automations`、`.lark-cli`、`runtime/`）用 Windows 目录 junction 指向真实位置。
- **原因**：框架（WorkBuddy）有硬编码发现逻辑，无法改名/移动；既要"3 秒看懂目录"，又不破坏框架。
- **验证**：Node `fs` / `ls -R` / `cmd dir /s` 均正常遍历。⚠️ Git Bash `find` **不**遍历 junction（已知行为，不影响功能）。

### D2 — Skill 扁平一级 + yushu_ 命名空间
- **决策**：所有 Skill 扁平放在 `01_Skill能力库（Skills）/`，`yushu_数字_中文_英文` 命名。
- **红线**：跨项目通用工具型 Skill 才放 user-level（`~/.workbuddy/skills/`）；本工程 Skill 一律工程内。

### D3 — 飞书 Base 为唯一事实源
- **决策**：不维护本地主数据库；本地 `04_数据中心` 只存 Schema（版本化定义）+ Runtime 状态 + 系统配置。
- **原因**：多 Agent 协作需要共同事实源；消除"数据在哪"的模糊。

### D4 — 数据模型中心（Schema 中心）独立
- **决策**：字段级定义唯一来源 = `04_数据中心/数据模型（Schema）`；系统注册表（yushu_00）只登记资产清单，不维护字段。先定义 Schema 再写代码。

### D5 — v1.2 输入解析引擎"搬家不装修"拆分（进行中→已冻结迁移）
- **决策**：旧 `input_parser.py`（2395 行巨石）拆分为 `main.py`(入口) + `router.py`(路由) + `handlers/`(17 业务 handler)；旧逻辑冻结为 `input_parser_old.py`（md5 `a60437b6cfdd4eb8a0bf226865d751ef`）作 Frozen Behavior Reference；`input_parser.py` 改为 12 行 shim。
- **状态**：Step2-4 全部 17/17 handler 迁移并冻结；Step2-5a `main.py` 为正式入口；Step2-5b shim 就位；测试基线 194/194 PASS，Golden 7+3。
- **遗留**：Router 仅保留 `_call_standard` 旧桥（展示层兼容缓冲），Phase 5 Service/format_output 治理时切断。

### D6 — competition 作为 Adapter（不重构状态机）
- **决策**：`handlers/competition.py` → `competition_manager.main_handler()`，通过 `config.py + lark_bridge._run_lark_cli` 调 `set_config`。禁止复制/重构其状态机。

### D7 — BodyOS Garmin 三层契约（2026-07-29 固化）
- 三层文件名不改：`raw_garmin_365d.json`(镜像) → `body_os_dataset_365d.json`(清洗,统计唯一入口) → `body_os_today_energy.json`+`_energy_status.json`(运行态)。
- 命名 `body_battery_score`（展示「身体可用能量」，**禁用「精神电量」**）；`valid_start` 唯一来源 `body_os_config.json`。

### D8 — 训练计划"同时建飞书任务"约定（2026-07-30）
- **决策**：多日训练计划同时建飞书任务（不进执行库 Base），`--due` 设训练当天，`--description` 含动作清单 + "练完用 #训练 打卡"。
- **原因**：只建日历→排程引擎读不到训练；建 Base→与排程引擎建的飞书任务重复。

---

### D9 — 前端逻辑链 + 编排层 + 能力插件（2026-09-26）

- **决策**：采用 ADR-010 的五层结构；用户只面对 Capture、Plan、Today、Adjust、Review、Explore。
- **插件边界**：Skill 是使用说明，Plugin 是实际能力；没有 Manifest 和调用合同的模块不视为正式插件。
- **迁移方式**：采用 Strangler Migration，现有 Runtime、Gateway、handler 和事实源不推翻。

### D10 — 联邦式事实源取代“全域单库”（2026-09-26）

- **决策**：飞书继续是执行态事实源，但不再被描述为所有数据的唯一事实源。
- **历史关系**：D3 保留为历史记录，其适用范围收窄为执行态和移动触达数据。
- **知识正文**：D:\Knowledge，经 Knowledge Gateway。
- **信息投影**：information_system SQLite。
- **身体原始数据**：Garmin / Body Dataset。
- **治理**：Core 统一理解，不要求统一物理存储。

### D11 — 动作权限不等于 Agent 自治等级（2026-09-26）

- **决策**：Observe、Suggest、Autonomous、Approval Required 用于单个动作的策略判断。
- **不变量**：Agent 自治等级上限保持 Level 2；需要审批不表示提升到 Level 3。

---

## 二、技术红线（违反即破坏系统）

1. **Git 陷阱**：`.gitignore` 必须覆盖 `lark-cli/`、`node_modules/`、`09_临时文件（Temp）/`、`运行状态（Runtime）/`、`.lark-cli/`。绝不提交密钥/依赖/状态。
2. **runtime 路径**：handler 写共享 runtime 必须上溯到引擎根（`dirname(dirname(__file__))`），**禁止落到 `handlers/runtime/`**。
3. **datetime 测试**：不要 patch `datetime.datetime.now`（C 级不可变）；用 `mock.patch.object(module, "datetime", fake_datetime_module)`。
4. **跨引擎 lazy import 测试**：必须控制 `sys.modules` 缓存与 import timing，否则 mock 被真实模块覆盖。
5. **飞书写入**：必须经 yushu_04 飞书操作 Processor，禁止 handler 直接裸调 lark-cli 写库（除已约定的 competition Adapter 路径）。

---

## 三、已知坑 / 外部阻断点

| 项 | 状态 | 说明 |
|----|------|------|
| lark-cli Go 二进制偶发 `open.feishu.cn TLS handshake timeout` | 已知 | curl/schannel 正常，重试可恢复 |
| `.lark-cli/` 是 junction，真实落点 `06_外部连接/飞书/lark-cli/` | 已知 | 勿在根 `.lark-cli/` 写，会落到真实目录 |
| `calendar_sync.py` 仍用每日排程引擎独立 runtime | 已知 issue | Phase 5 治理 |
| 外部知识库（LLM Wiki / MCP）接入 | ✅ 已迁移 | 知识库已转移至外部 `D:\Knowledge`（2026-08），仓库内目录随迁移删除；原阻断说明（app `mcpEnabled=false`、无写接口等）仅作历史记录 |
| `_call_standard` 旧桥 | 遗留 | Phase 5 治理切断 |

---

## 四、未决 / 待做（Roadmap 关联）

- Phase 5：Service 层 + format_output 治理，切断 `_call_standard` 旧桥；治理 `calendar_sync.py` 独立 runtime。
- 训练/营养/身体指标三表（16/17/18）正式落库飞书。
- ~~外部知识库真正可用~~（已完成：知识库迁移至外部 `D:\Knowledge`）。
- 排程引擎 `calendar_sync.py` 独立 runtime 收敛到引擎根。
