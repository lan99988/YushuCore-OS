# 个人混合管理系统（Personal AI OS）

> 以飞书多维表格为数据中枢、WorkBuddy 为输入口、Agent 每日推送的**个人 AI 管理操作系统**。
> 主攻方向：考研（数学二 / 英语二 / 政治 / 408）+ 日常项目管理。

---

## 命名原则

打开目录 3 秒知道这个文件夹负责什么。

- 文件夹：**`编号_中文名称（英文标识）`** —— 中文主、英文辅，绝不反过来。
- Python 文件：保持 `english_snake_case`。
- Markdown 文件：`中文名称.md`。

顶层用两位数字编号保证固定排序（00 在最上，09 在最下）。

---

## 目录结构

```
个人混合管理系统/
├── 00_系统核心（System）/        系统注册表、Agent 指南、工作流定义、长期记忆、系统配置
│   ├── Agent指南/                 agent-guide.md —— 所有 Agent 的通用规则与共享状态机制
│   ├── 工作流定义/               ⚠️ 软链 → .workbuddy/automations（框架自动化定义）
│   ├── 长期记忆/                 ⚠️ 软链 → .workbuddy/memory（项目记忆）
│   ├── 系统配置/
│   └── (详见 Agent指南/agent-guide.md)
│
├── 01_Skill能力库（Skills）/      所有 Skill（扁平一级，yushu_ 前缀命名空间）
│   ├── yushu_00_Skill注册中心_Registry/   系统总 SKILL.md（含多 Agent 协作规则）
│   ├── yushu_01_输入解析引擎_Router/
│   ├── yushu_02_意图分类_Router/
│   ├── yushu_03_快速查询_Router/
│   ├── yushu_04_飞书操作_Processor/
│   ├── yushu_05_问答校准_Processor/
│   ├── yushu_06_每日排程_Processor/
│   ├── yushu_07_习惯管理_AtomicHabits/
│   ├── yushu_08_深度工作_DeepWork/
│   ├── yushu_09_比赛管理_Competition/
│   ├── yushu_10_身体总管_BodyController/
│   ├── yushu_11_力量塑形_StrengthSystem/
│   ├── yushu_12_营养管理_NutritionSystem/
│   ├── yushu_13_恢复管理_RecoverySystem/
│   └── yushu_14_身体分析_BodyAnalytics/
│
├── 02_执行引擎（Engine）/         纯后台 Python 引擎（不可见，被 Skill/自动化调用）
│   ├── 输入解析引擎/             input_parser.py —— 前缀指令解析 → 飞书 Base
│   ├── 每日排程引擎/             daily_scheduler.py + calendar_sync.py
│   ├── 数据分析引擎/             analytics_engine.py
│   └── 复盘分析引擎/             weekly_deep_review.py
│
├── 03_领域模块（Modules）/        各业务域的数据 + 程序
│   ├── 习惯管理（Atomic-Habits）/
│   ├── 深度工作（Deep-Work）/
│   └── 比赛管理（Competition）/程序/competition_manager.py
│
├── 04_数据中心（Data）/          所有持久化数据
│   ├── 同步记录/  排程配置/  数据库/  精力状态/
│   └── 运行状态（Runtime）/     ⚠️ 软链 → runtime/
│
├── 05_自动化工作流（Automation）/
│   └── 脚本/                     create_dashboard.py、deep_work_reminder.py 等
│
├── 06_外部连接（Integration）/
│   ├── 知识库（Knowledge Base）/LLM Wiki/
│   └── 飞书（Feishu）/lark-cli/  ⚠️ 软链 → .lark-cli
│
├── 07_系统文档（Docs）/           SYSTEM_BLUEPRINT.md、NEW_AGENT_ONBOARDING.md、各模块设计文档、plans/
│
├── 08_工具脚本（Tools）/
│   └── 系统维护/                  fix_feishu_hosts.ps1 等
│
├── 09_临时文件（Temp）/
│   ├── 导入缓存/   编译缓存（__pycache__）/
│
└── runtime/                      ⚠️ 软链 → 04_数据中心（Data）/运行状态（Runtime）
```

---

## 关键设计决策：junction 桥接

框架（WorkBuddy）在以下路径有**硬编码发现逻辑**，无法改名或移动：

| 框架硬编码路径 | 真实内容落点 | 桥接方式 |
|---|---|---|
| `.workbuddy/skills/*/SKILL.md` | `01_Skill能力库（Skills）/`（扁平一级） | 目录 junction |
| `.workbuddy/memory/` | `00_系统核心（System）/长期记忆/` | 目录 junction |
| `.workbuddy/automations/` | `00_系统核心（System）/工作流定义/` | 目录 junction |
| `.lark-cli/` | `06_外部连接（Integration）/飞书（Feishu）/lark-cli/` | 目录 junction |
| `runtime/` | `04_数据中心（Data）/运行状态（Runtime）/` | 目录 junction |

**策略**：真实文件按中文命名体系存放，原框架路径用 Windows 目录 junction（`mklink /J`）指向真实位置。
对框架与工具完全透明（Node `fs` / `ls -R` / `cmd dir /s` 均正常遍历），既满足"3 秒看懂目录"，又不破坏任何硬编码发现逻辑。

> 注意：Git Bash 的 `find` 命令**不**遍历 junction（返回 0），这是 `find` 的已知行为，与框架使用的 Node `fs` 无关，不影响功能。

---

## 引擎跨目录导入

引擎分散在 `02_执行引擎（Engine）` 的各子目录，彼此 `import` 时通过各引擎头部的 **sys.path 引导块** 自动把兄弟引擎目录加入 `sys.path`：

```python
# 每个引擎顶部都有（路径随所在目录不同）
def _ensure_engine_paths():
    _engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in [输入解析引擎, 每日排程引擎, 数据分析引擎, 复盘分析引擎, ...]:
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
_ensure_engine_paths()
```

**运行方式**（脚本自身目录会被加到 `sys.path[0]`，引导块再补兄弟目录）：

```bash
python "02_执行引擎（Engine）/输入解析引擎/input_parser.py" "#复盘 7"
python "02_执行引擎（Engine）/每日排程引擎/daily_scheduler.py" --analytics
```

---

## 常用入口

- **系统蓝图**：`07_系统文档（Docs）/SYSTEM_BLUEPRINT.md`
- **新 Agent 入职**：`07_系统文档（Docs）/NEW_AGENT_ONBOARDING.md`
- **Agent 通用规则**：`00_系统核心（System）/Agent指南/agent-guide.md`
- **飞书 Base Token**：`TtzIboiQQaPgfVszO2vc56wLnof`（执行库 `tblNQCB4pn6Rso4a`）

---

## 重构记录

- 2026-07-23：按"中文主名 + 英文辅标"命名体系整体重构目录；用 5 个 junction 桥接框架硬编码路径，引擎加 sys.path 引导块修复跨目录 import；修正所有 stale 路径引用（agent-guide.md、competition SKILL.md、自动化「每周复盘」、脚本 usage docstring）。
