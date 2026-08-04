# 技能索引（SKILL_INDEX）

> 配套：`SYSTEM_BLUEPRINT.md` · `ARCHITECTURE.md` · `DATA_MODEL.md` · `WORKFLOW.md` · `DECISION_LOG.md`
> 最后更新：2026-08-03。本文是"模块骨架"层——15 个工程内 Skill 各自管什么、怎么触发、谁调谁。

---

## 一、Skill 存放约定（方法三：目录结构）

```
01_Skill能力库（Skills）/        ← 真实落点（扁平一级）
├── yushu_00_Skill注册中心_Registry/   SKILL.md  ← 系统总入口（根节点）
├── yushu_01_输入解析引擎_Router/
├── yushu_02_意图分类_Router/
├── yushu_03_快速查询_Router/
├── yushu_04_飞书操作_Processor/
├── yushu_05_问答校准_Processor/
├── yushu_06_每日排程_Processor/
├── yushu_07_习惯管理_AtomicHabits/
├── yushu_08_深度工作_DeepWork/
├── yushu_09_比赛管理_Competition/
├── yushu_10_身体总管_BodyController/
├── yushu_11_力量塑形_StrengthSystem/
├── yushu_12_营养管理_NutritionSystem/
├── yushu_13_恢复管理_RecoverySystem/
└── yushu_14_身体分析_BodyAnalytics/
```

**红线**：Skill 扁平一级；文件夹名「中文主 + 英文辅」；真实目录经 junction 暴露给框架 `.workbuddy/skills/`。另有 2 个 user-level（非工程内）：`yushu_import-project`、`yushu_multi-agent-collaboration`。

---

## 二、决策树（Agent 先读 yushu_00 注册中心）

```
用户输入
├─ 以 # 开头 → yushu_01 输入解析引擎 Router
│   (#任务/#灵感/#Bug/#账单/#社交/#创作/#知识/#孵化/#复盘/#精力/#配置/#身体/#训练/#营养/#恢复/#体测/#临时/#同步任务框)
├─ 无 # 且与个人管理相关 →
│   ├─ 明显动作 → yushu_02 意图分类(type:task)
│   ├─ 想法/观点 → yushu_02(type:idea)
│   ├─ 报错/异常 → yushu_02(type:bug)
│   ├─ 状态/精力 → yushu_02(type:energy)
│   ├─ 身体/训练/Garmin → yushu_10 身体总管
│   ├─ 进度查询 → yushu_03 快速查询
│   ├─ 今日安排/排程 → yushu_06 每日排程
│   └─ 导入/新建项目 → yushu_import-project(user-level)
├─ 与个人管理无关 → 直接聊天，不加载 skill
└─ yushu_02 字段不全 → yushu_05 问答校准 → 回 yushu_02
```

**铁律**：① 一次只加载一个 skill，处理完按"后续流程"加载下一个。② 飞书**写入必须**经 yushu_04 飞书操作 Processor（唯一写入口）。

---

## 三、各 Skill 职责速查

| Skill | 层/角色 | 触发 | 职责 | 关联数据 |
|-------|---------|------|------|----------|
| yushu_00 注册中心 | 根 | 被动读 | Base Token / 18 资产注册表 / lark-cli 模板（只读"有什么"） | 全部 |
| yushu_01 输入解析 Router | 路由 | `#` 前缀 | 委托 Engine `main.py → router.dispatch` | 全部业务表 |
| yushu_02 意图分类 Router | 路由 | 自然语言 | 判别 task/idea/bug/energy，提取意图 | 执行库/灵感/ Bug |
| yushu_03 快速查询 Router | 路由 | 进度/统计查询 | 查完成率/到哪了/多少了 | 科目进度/执行库 |
| yushu_04 飞书操作 Processor | 处理器 | 需写 Base/建任务 | **唯一写入口**（record-upsert / task +create / im send） | 全部 |
| yushu_05 问答校准 Processor | 处理器 | 字段缺失/意图模糊 | 补字段后回 yushu_02 | — |
| yushu_06 每日排程 Processor | 处理器 | 排程/时间轴/推送 | 排程算法 + 模块提醒 + 日历同步编排 | 全部业务表 |
| yushu_07 习惯管理 | 业务 | `#习惯`/`#习惯打卡`/`#习惯进度` | Atomic Habits 创建/打卡/进度 | 习惯表 |
| yushu_08 深度工作 | 业务 | `#深度`/`#深度规划`/`#深度记录`/`#复盘深度` | 深度目标/记录/复盘（4DX） | 深度工作表 |
| yushu_09 比赛管理 | 业务 | `#比赛` | 比赛 6 阶段生命周期（Adapter→competition_manager） | 比赛表 |
| yushu_10 身体总管 | 业务 | `#身体`/训练决策/Garmin 解读 | Body OS 总控 | Energy/Training/BodyMetrics |
| yushu_11 力量塑形 | 业务 | `#训练` | 力量/跑步记录 | TrainingLog |
| yushu_12 营养管理 | 业务 | `#营养` | 蛋白/饮水/补剂 | NutritionLog |
| yushu_13 恢复管理 | 业务 | `#恢复` | 睡眠/酸痛/压力 | BodyMetrics/Recovery |
| yushu_14 身体分析 | 业务 | `#体测` | 趋势/Body Score | BodyMetrics |

---

## 四、输入解析引擎 Router 系列（与 Engine 的对应关系）

`yushu_01` 是 Skill 层路由壳；真正的分发在 Engine `router.py` 的 `ROUTES` / `ROUTE_HANDLERS`：

| Router 前缀 | Engine handler | 说明 |
|-------------|----------------|------|
| `#临时` | `handlers/lightweight` | 临时任务短路 |
| `#精力` | `handlers/energy` | 精力状态（调 BodyOS） |
| `#配置` | `handlers/config_cmd` | 推送配置 |
| `#孵化` | `handlers/hatch` | 灵感孵化 |
| `#复盘` | `handlers/review` | 复盘 |
| `#排程到日历`/`#日历` | `handlers/schedule_calendar` | 手动同步日历 |
| `#深度规划`/`#深度记录`/`#深度` | `handlers/deep_plan`/`deep_record`/`deep_work` | 深度工作 |
| `#注意力审计` | `handlers/attention_audit` | 社媒倒推 |
| `#习惯*` | `handlers/habit*` | 习惯三指令 |
| `#比赛` | `handlers/competition` | 比赛（Adapter） |
| `#身体`/`#训练`/`#营养`/`#恢复`/`#体测` | `handlers/body_os` | Body OS 统一入口 |
| `#同步任务框` | `handlers/sync_taskbox` | 任务框同步 |
| `#任务`/`#灵感`/`#Bug`/`#账单`/`#社交`/`#创作`/`#知识`… | `handlers/standard_record`（经 `_call_standard` 旧桥） | 标准记录路径 |

---

## 五、注册中心"数据资产注册表"要点

- 18 个数据资产分 5 大类：01 核心执行 / 02 成长管理 / 03 项目管理 / 04 知识关系 / 05 决策分析。
- 字段级定义一律在 `04_数据中心/数据模型（Schema）`，注册表不维护字段。
- lark-cli 命令模板集中维护在注册表，**变更只改一处**。
- 统一错误处理（网络超时重试 1 次 / 401 查 `--as=user` / 400 对照字段 / 404 不重试 / 未知错误原样返回）。
