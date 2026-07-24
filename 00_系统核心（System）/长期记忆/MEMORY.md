# 项目记忆

## 系统概要
个人混合管理系统 — 以飞书多维表格为数据中枢，WorkBuddy为输入口，Agent每日推送的闭环系统。
主攻方向：考研（数学二、英语二、政治、408）+ 日常项目管理。

## 飞书Base信息
- Base Token: `TtzIboiQQaPgfVszO2vc56wLnof`
- 执行库: tblNQCB4pn6Rso4a
- 灵感库: tblx1ZaQGwXvoJhj
- Bug库: tblPpPputYMACtQ5
- 科目进度基线: tblQnjCO03WjQ7GC

## 系统文档
- `SYSTEM_BLUEPRINT.md` — 完整蓝图（含API操作参考）

## 实施路线
- [x] Phase 1：飞书多维表格数据底座
- [x] Phase 2a：输入流打通（指令解析引擎）— 已新增 #孵化、#复盘、排程去重、硬骨头多格式
- [x] Phase 2b：财务符号修正、金额容错、科目基线动态权重
- [ ] Phase 2c：交互卡片推送（后续可选）
- [x] Phase 3：每日排程与推送 — 进度条可视化、社交阈值自适应
- [x] Phase 4：每周复盘自动化（PAUSED，周日21:00触发）
- [ ] Phase 4b：复盘报告8维深度分析（待完善prompt）

## 科目信息
- 数学二 → 科目类别：数学（考试日2026/12/20，每天3.5h）
- 英语二 → 科目类别：英语（考试日2026/12/19，每天2.5h）
- 政治 → 科目类别：政治（考试日2026/12/19，每天1.5h）
- 408 → 科目类别：专业课（考试日2026/12/20，每天3.5h）

## 每日可用时长
- 默认：10小时
- 精力差时：缩至8小时
- 四科合计建议：11小时（略超默认，排程时按权重取舍）

## 2026-06-30 全系统优化成果
- 修复3个代码BUG（dead code、财务符号、硬骨头检测）
- 新增4个指令（#孵化、#复盘、排程去重、完成率推断）
- 每周复盘自动化（PAUSED）
- 3项体验优化（进度条、金额容错、社交自适应）

## 2026-07-01 Skill 原子化拆分
旧巨石 skill（根 SKILL.md 252行 + 随手录 803行）拆为 6 个原子 skill：
- ① 个人混合管理系统 — 系统注册表（`skills/SKILL.md`，仅表定义+Token）
- ② 输入解析引擎 — 前缀指令+变量提取（`skills/输入解析引擎/SKILL.md`）
- ③ 随手录-意图分类 — 无前缀NL分类（`skills/随手录-意图分类/SKILL.md`）
- ④ 随手录-问答校准 — 多轮对话补充（`skills/随手录-问答校准/SKILL.md`）
- ⑤ 随手录-飞书操作 — Base写入+任务创建（`skills/随手录-飞书操作/SKILL.md`）
- ⑥ 每日排程算法 — 排程+进度条+v2.0全模块（`skills/每日排程算法/SKILL.md`）
- ⑦ 多Agent协作（user-level，不动）
- ⑧ import-project（user-level，不动）
- 删除 `skills/随手录/` 目录（旧巨石）
- 每个 skill 顶部含「纲要」「触发」「输出」「后续流程」交互协议
- 设计文档：`docs/plans/2026-07-01-skills-split-design.md`

## 2026-07-01 飞书日历同步工程 🆕
### 新增文件
- `calendar_sync.py` — 日历同步独立模块
- `docs/plans/2026-07-01-calendar-sync-design.md` — 设计文档

### 修改文件
- `daily_scheduler.py` — 排程后自动同步到日历，冲突信息追加到推送消息
- `input_parser.py` — 新增 `#排程到日历` / `#日历` 手动触发指令
- `docs/SYSTEM_BLUEPRINT.md` — 新增第七节「飞书日历同步」

### 核心能力
- 学习时段自动写入飞书日历（🔴高/🟡中/🟢低 三色区分）
- 冲突检测（+freebusy）+ 冲突提醒
- 自动顺延（+suggestion 找下一个空闲时段）
- 双模式触发：排程器自动跟随 + 手动 `#排程到日历`
- 运行日志：`runtime/_calendar_log.json`

### 冲突处理（三层）
1. 查询忙闲 → 检测重叠
2. 推送提醒告知冲突（可并行/需重排）
3. 用户选择后自动顺延到下一个空闲时段

## 2026-07-03 lark-cli 调用规范统一
- lark-cli 独立运行时的 `--as user` 身份须单独配置（`config init --new` + `auth login`）
- **调用方式**：所有 Python 脚本统一使用直调 Node.js（`node.exe` + `run.js`），不经过 bash/cmd 包装层
  - 路径：`NODE_PATH` = `C:\Users\26326\.workbuddy\binaries\node\versions\22.22.2\node.exe`
  - 入口：`CLI_JS` = `C:\Users\26326\.workbuddy\binaries\node\workspace\node_modules\@larksuite\cli\scripts\run.js`
  - 原因：规避 shell 转义问题（反引号、特殊字符）+ 避免 bash/cmd 包装层路径解析差异
- 相关文件：`scripts/deep_work_reminder.py`（已修改）, `calendar_sync.py`（待统一）

## 2026-07-13 任务分类机制（正式 vs 轻量）🆕
### 判定规则（核心）
- **无 `#临时` 标记 = 正式任务** → 写入执行库（Base），排程器读取后纳入每日作战时间轴，并自动在任务框建对应任务。
- **带 `#临时` 标记 = 轻量任务** → 仅入飞书任务框（标题加 `[临时]` 前缀），**不写执行库**，不进时间轴。

### 新增指令（input_parser.py）
- `#临时 买牛奶` 或 `#任务 买牛奶 #临时` → 仅创建任务框任务，跳过 Base 写入。
  - 实现：`handle_lightweight_task()`，用 `task tasks create --data @file --as user`。
- `#同步任务框`（+ `--dry-run`）→ 扫描任务框，把未入库的正式任务拉回执行库。
  - 分类：① `[临时]` 前缀→跳过 ② status=done→跳过 ③ 已在执行库→跳过(去重) ④ 其余→写入执行库。
  - 实现：`handle_sync_taskbox()`。

### 修复的坑
- `base +record-list` 的 `--limit` 上限为 200（非 500），超限会静默失败→去重失效。`#同步任务框` 已改为 `--limit 200` + `--offset` 分页，且 Base 读取失败**硬报错**而非当空集。
- 任务框列表接口对新任务有短暂索引延迟（eventual consistency），新建临时任务可能暂不出现在 `#同步任务框` 列表——不影响功能。

### 文档
- `docs/任务分类机制.md` — 完整判定规则 + 流程图 + 运维要点

## ⚠️ 已知网络问题：lark-cli Go 二进制 TLS 握手超时（2026-07-14）
- **现象**: lark-cli (Go 二进制) → `open.feishu.cn` 的 TLS 握手超时，报 `net/http: TLS handshake timeout`
- **对比**: curl/schannel 正常工作（0.2s），`mcp.feishu.cn` 端点也可达
- **可能根因**: DNS 路由到特定 CDN IP 时，该 IP 的 TLS 握手对 Go/OpenSSL 的包丢弃（read 0 bytes），但 curl/schannel 正常
- **当前应对**: 重试可恢复（临时网络波动）
- **长期建议**: 如频繁出现，考虑在 hosts 文件固定 `open.feishu.cn` 到已知正常 IP

## 2026-07-15 比赛管理模块 🆕
### 新增文件
- `competition_manager.py` — 比赛管理独立模块，处理 `#比赛` 全部子命令
- Base 表：**比赛管理表**（tblKPdoxMHy7FuV7，28 字段，单表 6 阶段全流程 + 2 个附件字段 + 比赛链接）
- Skill 包：`.workbuddy/skills/competition-manager/`（含 SKILL.md + schema.md + competition_manager.py）

### 修改文件
- `input_parser.py` — 4 处集成（TABLES + PREFIX_MAP + dispatch + format_output）
- `docs/SYSTEM_BLUEPRINT.md` — 新增比赛管理表和数据流

### 命令体系
- `#比赛 创建 [名称] 【日期：】【地点：】【人员：】` — 创建比赛
- `#比赛 [名称] [阶段] 【key：value】` — 更新指定阶段
- `#比赛 [名称] 初赛 跳过` — 跳过初赛（仅一轮）
- `#比赛 [名称] 决赛 不适用` — 无决赛
- `#比赛 列表` — 全部比赛总览（含 ASCII 进度条）
- `#比赛 [名称]` — 单场比赛详情
- `#比赛 帮助` — 帮助信息
- `#比赛 [名称] 上传凭证 <图片路径>` — 上传凭证到「报名费凭证」（报名费/报销通用）
- `#比赛 [名称] 上传报销 <图片路径>` — 同上，指向「报名费凭证」
- `#比赛 [名称] 上传奖状 <图片路径>` — 上传奖状截图到「奖状图片」字段
- 所有命令支持 `--dry-run`

### 附件能力
- 新增 Base 字段：`报名费凭证`（attachment）、`奖状图片`（attachment）
- 使用 `lark-cli base +record-upload-attachment` 上传，文件存储在飞书云空间
- 命令自动处理 Windows 路径（D:\、C:\）和相对路径
- 上传时自动复制文件到当前目录以满足 lark-cli 相对路径安全要求，完成后自动清理

### 坑点记录
- lark-cli 1.0.63 中 `+record-update` 不存在，用 `+record-batch-update` 替代
- `+record-batch-update` 的 JSON 格式为 `{"record_id_list":[...],"patch":{...}}`
- text 字段的 style.type 应为 `"plain"` 而非 `"text"`
- datetime 字段的 style.format 应为 `"yyyy/MM/dd"`（小写）非 `"YYYY/MM/DD"`
- `+record-upload-attachment` 的 `--file` 参数必须是当前目录下的相对路径，不接受绝对路径`## 2026-07-16 系统修复：字段精简 + 上传逻辑修正 + Skill重写
- **字段精简**：删除冗余 `奖状已上传`(checkbox)，Base从28→27字段。`_calc_stage_statuses`/`handle_update`/`handle_detail` 全部不再引用该字段
- **上传逻辑修正**：新增 `#比赛 [名称] 上传报销 <路径>`→「报名费凭证」。成绩阶段移除 `奖状已上传` 自动置True逻辑。修复 main_handler 上传检测用分词匹配替代substring匹配
- **字段排序**：设计27列逻辑顺序方案，需在Base UI拖拽。ID字段不可编辑，建议按日期排序视图
- 修复 handle_detail 函数定义丢失的遗留 bug
- **SKILL.md v1.1.0**：重写为AI自主执行说明书，含输入解析规则/命令构造精确模板/确认协议/错误处理/考试自动解析指南/版本历史
### 架构决策
- **工具下沉**：不再找轻量项目管理工具，自建分析引擎作为纯后台数据分析层
- **飞书 Base 做可视化前端**，engine 做数据采集/分析/持久化
- **零外部依赖**：不新增服务/容器，纯 Python + lark-cli + SQLite

### 新增文件
- `analytics_engine.py` — 分析引擎核心模块

### 修改文件
- `daily_scheduler.py` — 新增 `--analytics` 标记，排程后自动触发分析

### 分析能力
- 科目进度分析（完成率 + 剩余天数 + 赶进速率）
- 任务完成趋势（滚动窗口完成率，按科目/时间分布）
- 深度工作统计（周累计、日均、心流分布、第一勺率）
- 异常检测（中断日、科目失衡、浮浅过载）
- 本地 SQLite 快照（`runtime/_analytics.db`，支持历史趋势查询）

### 使用方式
- `python analytics_engine.py` — 完整运行
- `python analytics_engine.py --weekly --summary` — 周报摘要
- `python daily_scheduler.py --analytics` — 排程+分析链式运行

## 2026-07-23 目录命名体系整体重构（重要约定）

### 新顶层结构（编号_中文名称（英文））
- `00_系统核心（System）` / `01_Skill能力库（Skills）` / `02_执行引擎（Engine）` / `03_领域模块（Modules）`
- `04_数据中心（Data）` / `05_自动化工作流（Automation）` / `06_外部连接（Integration）` / `07_系统文档（Docs）`
- `08_工具脚本（Tools）` / `09_临时文件（Temp）`

### junction 桥接（框架硬编码路径不可改名，用软链透明桥接）
| 框架路径 | 真实落点 |
|---|---|
| `.workbuddy/skills` | `01_Skill能力库（Skills）`（扁平一级 + 数字前缀） |
| `.workbuddy/memory` | `00_系统核心（System）/长期记忆` |
| `.workbuddy/automations` | `00_系统核心（System）/工作流定义` |
| `.lark-cli` | `06_外部连接（Integration）/飞书（Feishu）/lark-cli` |
| `runtime` | `04_数据中心（Data）/运行状态（Runtime）` |

### 引擎跨目录 import 约定
- 各引擎头部有 `_ensure_engine_paths()` 引导块，把兄弟引擎目录加入 `sys.path`。
- 运行脚本时其自身目录进 `sys.path[0]`，引导块再补兄弟目录。
- 运行示例：`python "02_执行引擎（Engine）/输入解析引擎/input_parser.py" "#复盘 7"`

### 命名红线
- Skill 必须**扁平一级**（框架只扫 `.workbuddy/skills/*/SKILL.md`，不递归），用数字前缀排序。
- 文件夹名 **中文主 + 英文辅**，绝不反过来。
- Git Bash `find` 不遍历 junction（返回 0），但框架 Node fs / `ls -R` / `cmd dir /s` 正常，不影响功能。

## 2026-07-24 v1.1 数据模型中心（Schema）🆕

### 核心原则（用户纠正）
- **Schema 是数据层真实世界的抽象，不是 Skill 的映射**：一 Skill 可操作多模型，一模型可被多 Skill 用；模型数 = 业务实体数。
- 真实飞书 Base 共 **15 张表**（非最初以为的 11）。

### 数据资产注册表（Data Registry）
- 位置：`01_Skill能力库（Skills）/00_Skill注册中心（Registry）/SKILL.md` 的 `## 数据资产注册表` 段。
- 职责：**只列「有哪些资产 / 飞书表 ID / 谁使用」**，**不再维护字段**。
- 15 个模型（编号/模型/中文/类型/飞书表）：
  - 01 Task(执行库 tblNQCB4pn6Rso4a) / 02 Idea(灵感库) / 03 Bug(Bug库) / 04 Energy(设计稿,无表) / 05 Habit(习惯追踪表 tblSRdG4P3XE75Ll) / 06 DeepWork(深度工作追踪表 tblmAz37er4CEbL0) / 07 SubjectProgress(科目进度基线 tblQnjCO03WjQ7GC) / 08 Competition(比赛管理表 tblKPdoxMHy7FuV7)
  - 09 Finance(财务流水表 tblPFKBGubeIYsfm) / 10 Social(社交关系表 tblt7uTkIcLhH7bs) / 11 Creation(创作素材表 tbl99pDAlTIDu7f5) / 12 Knowledge(知识笔记表 tblgtdx4h0EJjRrh) / 13 MultiRoundTracking(多轮次追踪表 tblJmOfDHV83RsIg) / 14 Project(项目管理 tblCnVUb327SQ9mS) / 15 StockStrategy(股市策略 tblVWrqa8fNCcCjA)
  - 注：根表「个人混合管理系统」(tblPxhRiJg8SfXxD) 为系统总览表，非业务资产。

### Schema 目录（字段定义唯一来源）
- `04_数据中心（Data）/数据模型（Schema）/`：5 大类分层 `01_核心执行`/`02_成长管理`/`03_项目管理`/`04_知识关系`/`05_决策分析` + `README.md`（设计原则/15模型总表/字段命名规则/标准结构）。
- `04_数据中心（Data）/数据版本（Version）/版本记录.md`：版本账本。
- **本批完成 8 个**（第一批，系统运行必须）：Task/Idea/Bug/Energy/Habit/DeepWork/SubjectProgress/Competition。其余 7 个（Finance/Social/Creation/Knowledge/Project 第二批；StockStrategy/MultiRoundTracking 第三批）待补。
- Schema JSON 标准结构：`model`/`中文名称`/`version`/`description`/`source_skill`/`feishu_table`/`fields[]`；字段**英文 name + 中文名称**；formula/auto_number/system_timestamp 标 `computed:true`。
- 类型归一化：text/enum/number/datetime/boolean/attachment/formula/auto_number/system_timestamp。
- Energy 为设计稿（`feishu_table:null`），待未来 Repository 落库。
