# 个人混合管理系统 · 全文件作用清单（2026-07-23）

> 范围：用户本次列出的全部文件/文件夹
> 说明：纯文本清单，无图片

---

## 一、顶层文件夹

### `llmwkiki/`
本地知识库应用（外部打包程序，非本项目源码）。
- `LLM Wiki/llm-wiki.exe`（79 MB）— LLM Wiki 桌面主程序
- `LLM Wiki/mcp-server/` — Node 写的 MCP 服务（`llm-wiki-mcp-server` v0.4.25，keywords: mcp / llm-wiki / knowledge-base），把本地知识库 API 暴露给 Agent 作为知识后端
- `LLM Wiki/pdfium/` — PDF 渲染引擎（MCP 服务读取 PDF 用）
- 文件夹内 1014 个文件绝大多数是 `mcp-server/node_modules` 的依赖（ts/js/json/map），不是手写代码

### `runtime/`
本地运行时状态（被 `.gitignore` 忽略，不入库）。
- `_analytics.db` — SQLite3 数据库，分析引擎的本地历史快照/趋势查询库
- `_calendar_log.json` — 日历同步日志（日期 / events / conflicts / cleared）
- `_energy_status.json` — 当前精力状态（date/status/raw），排程算法读取
- `_overflow_tracker.json` — 拖延根因追踪：连续 overflow 任务及其 streak
- `_schedule_config.json` — 排程自定义配置（今日可用时长 / 精力系数）
- `_sync_result.json` — 任务框同步结果（matched/updated/no_match 列表）

### `scripts/`
辅助脚本（由 `setup_workflows` 等一次性运行，或自动化触发）。
- `create_dashboard.py` — 在飞书 Base 创建仪表盘可视化组件
- `deep_work_reminder.py` — 深度工作提醒推送（给飞书发消息）
- `setup_workflows.py` — 在飞书 Base 创建/启用自动化工作流（灵感通知、Bug 通知、任务完成通知、灵感周检）
- `__pycache__/` — 编译缓存

### `.lark-cli/`
lark-cli 的本地配置与缓存。
- `config.json` — 飞书 app 凭证（appId `cli_aaca6c2e9af8dcb0`、user open_id `ou_...`、用户名"蓝"），密钥存系统 keychain
- `update-state.json` — lark-cli 最新版本（1.0.65）与检查时间戳
- `cache/` — 命令缓存；`logs/` — 运行日志

### `.workbuddy/`
WorkBuddy 项目元数据。
- `skills/` — 10 个 skill（见上一轮清单）
- `memory/` — 项目记忆（每日 `YYYY-MM-DD.md` 日志 + `MEMORY.md` 长期记忆 + `workflow-*.json` 工作流按钮定义）
- `automations/` — 6 个定时自动化定义目录（每个含 `memory.md`，如每日推送、灵感周检等）

### `__pycache__/`
Python 编译缓存（7 个 `.pyc`，对应各脚本编译产物），被 `.gitignore` 忽略。

### `docs/`
文档目录。
- 设计：`SYSTEM_BLUEPRINT.md`（完整蓝图）、`模块设计-飞书Base一体化扩展.md`、`多项目共享状态机制.md`、`参考资料-人生管理系统架构参考.md`、`DASHBOARD_DESIGN.md`、`NEW_AGENT_ONBOARDING.md`、`.skill.md`（早期 skill 描述）
- 机制：`任务分类机制.md`
- 计划：`plans/`（calendar-sync、skills-split、atomic-habits、deep-work 四个设计文档）
- 上轮产物：`skills-inventory-2026-07-23.md`、`skills-dependency-graph.svg`

---

## 二、顶层配置文件

### `.agent-guide.md`
新 Agent 入职指南：项目定位（飞书 Base 为数据中枢 + Agent 每日主动推送）、数据源（9 张表清单）、通用规则（共享状态三字段：责任人/状态/状态更新时间）、输入格式、`lark-cli` 速查。供新 AI 快速对齐上下文。

### `.gitignore`
忽略规则：`__pycache__/`、`*.pyc`、`runtime/`、`.workbuddy/`、`.agent-guide.md`、`Thumbs.db`、`.DS_Store`。即本地状态、缓存、Agent 引导文件不进版本库。

### `_lark_tmp_3e5c449e.json`
比赛管理的一次性**临时解析产物**：把某场比赛（"2026年人工智能技能应用赛"）的字段提取结果（名称/日期/费用/初赛/决赛等）暂存，供 `competition_manager` 写入前确认处理。命名含随机串，属临时文件。

### `fix_feishu_hosts.ps1`
PowerShell 修复脚本（需管理员运行）。根治 lark-cli(Go) 访问 `open.feishu.cn` 的 TLS 握手超时：将该域名固定到 `202.168.162.164`（该 IP 对 curl/schannel 正常），先备份再改写 `hosts`。对应已知网络问题。

---

## 三、核心 Python 脚本（系统引擎）

| 文件 | 行数 | 作用 | 对应 skill |
|------|-----|------|-----------|
| `input_parser.py` | 2375 | **总入口**。解析 `#` 指令与【】变量（`detect_prefix`/`extract_variables`）；各 `handle_*`：能量/配置/孵化/复盘/排程到日历/深度规划·记录·通用·复盘/注意力审计/习惯·打卡·进度/轻量任务/同步任务框；`insert_to_feishu`/`deduplicate_check` 写库；`main()` 路由 | 输入解析引擎（并 dispatch 到三个领域模块） |
| `daily_scheduler.py` | 1601 | **排程引擎**。`generate_schedule` 生成作战时间轴；`compute_4dx_scoreboard`（深度计分板）、`auto_fill_deep_work_record`（预填深度记录）、`query_habits`/`query_social_reminders`/`query_finance_summary` 等模块查询、`format_schedule_v2` 组装推送、`create_feishu_tasks`/`send_feishu_message` | 每日排程算法 |
| `competition_manager.py` | 772 | **比赛管理核心**。`handle_create/update/list/detail/upload_attachment/help`，`main_handler` 路由；27 字段六阶段流水线、附件上传、进度条 | competition-manager |
| `analytics_engine.py` | 1067 | **分析引擎**。类 `SubjectStatus/CompletionRecord/DeepWorkRecord/AnalysisReport`、`AnalyticsEngine` 主类；拉 Base 做科目进度/完成趋势/深度统计/异常检测，快照写入 `_analytics.db` | （独立分析层） |
| `calendar_sync.py` | 726 | **日历同步**。`check_date_freebusy`/`check_slot_freebusy`、`create_calendar_event`、`find_next_available_slot`、`sync_schedule_to_calendar`、`reschedule_conflict`、日志 | （排程引擎的日历扩展） |
| `weekly_deep_review.py` | 334 | **深度工作周报**。`fetch_deep_work_records` 读深度表，`generate_weekly_report` 生成 ASCII 周报，`send_feishu_message` 推送 | deep-work-feishu（周日 21:00 运行） |

---

## 四、一句话总览
- **入口/路由**：`input_parser.py`（解析一切 `#` 与自然语言意图，写库/派发）
- **排程/推送**：`daily_scheduler.py` + `calendar_sync.py` + `weekly_deep_review.py`
- **领域模块**：`competition_manager.py`（比赛）、`analytics_engine.py`（分析）
- **辅助/运维**：`scripts/*`、`fix_feishu_hosts.ps1`、`.lark-cli/`、`runtime/`
- **知识后端（外部）**：`llmwkiki/LLM Wiki`（MCP 服务）
- **元数据/文档**：`.workbuddy/`、`docs/`、`.agent-guide.md`、`.gitignore`
- **临时/缓存**：`_lark_tmp_3e5c449e.json`、`__pycache__/`
