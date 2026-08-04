# 个人混合管理系统 — 系统注册表

> 标准信息段（依据 `Skill规范.md` 模板）

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 个人混合管理系统 — 系统注册表 |
| 版本 | 1.0（稳定） |
| 状态 | 稳定 |
| 创建时间 | 2026-06-28 |
| 负责人 | 甲乙簿 |

## 功能定位

系统唯一入口与"有什么"登记表。定义 Base Token、全部数据表 ID、项目选项、字段清单、lark-cli 命令参考与统一错误处理。**不含行为逻辑**，其他 Skill 启动时第一件事读取它。

## 触发方式

被动读取——所有 Skill / Engine 启动时读取；也是 Agent 决策树的根节点。

## 输入

无（被动引用）。

## 输出

Base Token / 数据资产注册表（含飞书表 ID）/ 命令模板（供其他 Skill 引用）。字段级定义见 `04_数据中心（Data）/数据模型（Schema）`。

## 依赖

- 飞书 Base（只读元数据）
- lark-cli（命令定义）

## 数据

本文件维护「数据资产注册表」（有哪些资产 / 飞书表 ID / 谁使用）；字段级定义的唯一来源为 `04_数据中心（Data）/数据模型（Schema）`。自身不读写具体记录。

## 权限

- read：所有表元数据
- write：无
- admin：无

## 调用链

Agent → 系统注册表（取 Token/表ID）→ 各 Skill → Engine → 飞书 Base

## 测试

测试方式：人工核对表清单；`lark-cli auth status` 验证 Token 有效。
最后测试时间：2026-07-23

## 纲要

本项目的唯一入口。定义系统有哪些表、Base Token、项目选项列表。
**不包含行为逻辑**，只提供"有什么"。
其他所有 skill 启动时第一件事就是读本文件获取 Base Token、表 ID、以及 lark-cli 调用方式。

---

## 🚦 Agent 决策流程图

收到用户输入后，按此决策树选择第一个加载的 skill：

```
用户输入
│
├─ 以 # 开头 → 加载「yushu_01_输入解析引擎_Router」
│   (含 #任务/#灵感/#Bug/#账单/#社交/#创作/#知识/#孵化/#复盘/#精力/#配置/#身体/#训练/#营养/#恢复/#体测)
│
├─ 无 # 且与个人管理相关 →
│   ├─ 明显动作(做/看/完成/买/准备/需要/记得) → yushu_02_意图分类_Router(type: task)
│   ├─ 想法/观点/方法/知识(想到/觉得/发现/原来) → yushu_02_意图分类_Router(type: idea)
│   ├─ 报错/闪退/卡住/异常 → yushu_02_意图分类_Router(type: bug)
│   ├─ 状态/精力/累/困/没睡好 → yushu_02_意图分类_Router(type: energy)
│   ├─ 身体/训练/营养/恢复/体测/Garmin → 「yushu_10_身体总管_BodyController」
│   ├─ 进度查询(完成率/到哪了/多少了/进度) → 「yushu_03_快速查询_Router」
│   ├─ 今日安排/排程/时间轴/作战 → 「yushu_06_每日排程_Processor」
│   └─ 导入项目/新建项目 → 「yushu_import-project」(user-level)
│
├─ 与个人管理无关 →
│   └─ 直接聊天回复，不加载任何skill
│
└─ yushu_02_意图分类_Router 产出 type=task/idea/bug 但字段不全 →
    └─ 保留当前字段 → 加载「yushu_05_问答校准_Processor」补充字段 → 回 yushu_02_意图分类_Router 完善
```

**重要规则**：
- 一次只加载一个 skill，处理完后根据「后续流程」加载下一个
- 每次加载新 skill 前，先检查根 skill 获取 Base Token 等不变数据
- 飞书写入操作**必须**通过「yushu_04_飞书操作_Processor」skill 执行（唯一写入口）

---

## 核心数据

- **Base Token**: `TtzIboiQQaPgfVszO2vc56wLnof`
- **Base URL**: https://my.feishu.cn/base/TtzIboiQQaPgfVszO2vc56wLnof
- **操作身份**: `--as=user`
- **用户 open_id**: `ou_adf2c637b6ddd79c0af429ad5da3a746`

## 数据资产注册表（Data Registry）

> 本系统全部数据资产的权威清单。**字段级定义一律在 `04_数据中心（Data）/数据模型（Schema）`，此处不维护字段。**

数据定义唯一来源：`04_数据中心（Data）/数据模型（Schema）`

系统共有 18 个数据资产，分 5 大类（核心执行 / 成长管理 / 项目管理 / 知识关系 / 决策分析）。

| 编号 | 模型 | 中文名称 | 类型 | 飞书表ID | 主要用途 | 关联 Skill | Schema |
|------|------|----------|------|----------|----------|-----------|--------|
| 01 | Task | 任务 | 业务数据 | `tblNQCB4pn6Rso4a` | 日常/考研任务执行 | yushu_输入解析/yushu_飞书操作/yushu_排程 | ✅ |
| 02 | Idea | 灵感 | 业务数据 | `tblx1ZaQGwXvoJhj` | 想法暂存与孵化 | yushu_输入解析 | ✅ |
| 03 | Bug | 问题 | 业务数据 | `tblPpPputYMACtQ5` | 异常问题追踪 | yushu_输入解析 | ✅ |
| 04 | Energy | 精力状态 | 状态数据 | —（设计稿） | 排程/Body OS 输入 | yushu_排程/yushu_身体总管/yushu_恢复 | ✅ |
| 05 | Habit | 习惯 | 业务数据 | `tblSRdG4P3XE75Ll` | 习惯管理 | yushu_习惯 | ✅ |
| 06 | DeepWork | 深度工作 | 业务数据 | `tblmAz37er4CEbL0` | 深度记录与复盘 | yushu_深度 | ✅ |
| 07 | SubjectProgress | 科目进度基线 | 学习数据 | `tblQnjCO03WjQ7GC` | 学习进度追踪 | yushu_学习模块 | ✅ |
| 08 | Competition | 比赛 | 业务数据 | `tblKPdoxMHy7FuV7` | 比赛生命周期 | yushu_比赛 | ✅ |
| 09 | Finance | 财务流水 | 业务数据 | `tblPFKBGubeIYsfm` | 个人财务管理 | 财务模块 | ⏳ |
| 10 | Social | 社交关系 | 业务数据 | `tblt7uTkIcLhH7bs` | 关系维护 | 社交模块 | ⏳ |
| 11 | Creation | 创作素材 | 业务数据 | `tbl99pDAlTIDu7f5` | 内容生产管理 | 创作模块 | ⏳ |
| 12 | Knowledge | 知识笔记 | 知识数据 | `tblgtdx4h0EJjRrh` | 知识沉淀 | 知识模块 | ⏳ |
| 13 | MultiRoundTracking | 多轮次追踪 | 分析数据 | `tblJmOfDHV83RsIg` | 周期追踪分析 | 分析引擎 | ⏳ |
| 14 | Project | 项目管理 | 业务数据 | `tblCnVUb327SQ9mS` | 项目生命周期 | 项目模块 | ⏳ |
| 15 | StockStrategy | 股市策略 | 专业数据 | `tblVWrqa8fNCcCjA` | 投资策略管理 | 投资模块 | ⏳ |
| 16 | TrainingLog | 训练记录 | 业务数据 | —（待创建） | 力量/跑步统一训练记录 | yushu_身体总管/yushu_力量塑形/yushu_恢复/yushu_身体分析 | ✅ |
| 17 | NutritionLog | 营养记录 | 业务数据 | —（待创建） | 蛋白质/饮水/补剂执行 | yushu_身体总管/yushu_营养管理/yushu_身体分析 | ✅ |
| 18 | BodyMetrics | 身体指标 | 趋势数据 | —（待创建） | 体重/体脂/围度/静息心率/HRV | yushu_身体总管/yushu_恢复/yushu_身体分析 | ✅ |

> 注：飞书 Base 根表「个人混合管理系统」(`tblPxhRiJg8SfXxD`) 为系统总览表，非业务数据模型，不计入上述清单。

## 项目选项列表（多选下拉，共享枚举）

`考研 / 项目A / 项目B / 项目C / 项目D / 生活区 / 全局 / 考试`

---

## lark-cli 命令参考（集中维护，其他 skill 引用此处）

所有 skill 中需要用到的 lark-cli 命令在此定义。如命令有变更，**只改此处**。

### Windows 调用规范

所有 lark-cli 调用通过 Git Bash 执行：

```bash
# 命令模板
bash -c "lark-cli <command> [--params] --as=user"

# 带 JSON 参数时用 @tmpfile
# 1. 写临时文件
echo '{"key":"value"}' > _tmp_<uuid>.json
# 2. 调用
bash -c "lark-cli base +record-upsert --base-token=TtzIboiQQaPgfVszO2vc56wLnof --table-id=<id> --as=user --json @_tmp_<uuid>.json"
# 3. 清理
rm -f _tmp_<uuid>.json
```

**Git Bash 路径 fallback**：`Program Files\Git\usr\bin\bash.exe` → `Program Files\Git\bin\bash.exe` → `bash`
**编码 fallback**：utf-8 → gbk → gb2312 → cp936

### 通用读取模板

```bash
# 读取记录列表
lark-cli base +record-list \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=<TABLE_ID> \
  --as=user \
  --limit=200 \
  --format=json

# 搜索记录（带筛选条件）
lark-cli base +record-search \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=<TABLE_ID> \
  --as=user \
  --filter='{"conditions":[...]}'
```

### 通用写入模板

```bash
lark-cli base +record-upsert \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=<TABLE_ID> \
  --as=user \
  --json='@<tmpfile>.json'
```

### 通用更新模板

```bash
lark-cli base +record-batch-update \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=<TABLE_ID> \
  --as=user \
  --json='{"record_id_list":["<id>"],"patch":{...}}'
```

### 飞书任务模板

```bash
# 创建任务
lark-cli task +create \
  --summary="<标题>" \
  --description="<说明>" \
  --due="<毫秒时间戳>" \
  --assignee="<open_id>"

# 设提醒
lark-cli task +reminder --task-id="<guid>" --set="<分钟数>"
```

### 飞书消息推送模板

```bash
lark-cli im +messages-send \
  --user-id=ou_adf2c637b6ddd79c0af429ad5da3a746 \
  --markdown="<文本>" \
  --as=user
```

---

## 统一错误处理（所有 skill 通用）

所有飞书操作相关的 skill 遇到错误时，按此优先级处理：

| 错误类型 | 处理方式 |
|---------|---------|
| 网络超时（>30秒无响应） | **重试 1 次**，再失败则返回用户 |
| 权限错误（401/403） | 检查 `--as=user` 身份 + Base Token 是否有效 |
| 字段不匹配（400） | 对照本文件的字段清单修正字段名 |
| 记录不存在（404） | 返回"未找到记录"，不重试 |
| 临时文件错误 | 检查磁盘空间 + 写入权限 |
| 未知错误 | **将原始错误信息返回给用户**，不猜测、不隐藏 |

### 错误输出格式

```json
{
  "ok": false,
  "error": "[错误类型] 具体描述",
  "action": "重试中..." 或 "无需操作"
}
```

---

## 子技能索引

| skill | 路径 | 触发 |
|-------|------|------|
| yushu_01_输入解析引擎_Router | `yushu_01_输入解析引擎_Router/SKILL.md` | `#` 前缀指令 |
| yushu_02_意图分类_Router | `yushu_02_意图分类_Router/SKILL.md` | 无前缀自然语言 |
| yushu_03_快速查询_Router | `yushu_03_快速查询_Router/SKILL.md` | 进度/任务/统计查询 |
| yushu_04_飞书操作_Processor | `yushu_04_飞书操作_Processor/SKILL.md` | 需要写入 Base 或创建任务 |
| yushu_05_问答校准_Processor | `yushu_05_问答校准_Processor/SKILL.md` | 字段缺失/意图模糊 |
| yushu_06_每日排程_Processor | `yushu_06_每日排程_Processor/SKILL.md` | 排程/时间轴/推送 |
| yushu_10_身体总管_BodyController | `yushu_10_身体总管_BodyController/SKILL.md` | `#身体`/训练决策/Garmin 解读 |
| yushu_11_力量塑形_StrengthSystem | `yushu_11_力量塑形_StrengthSystem/SKILL.md` | `#训练`/力量/跑步记录 |
| yushu_12_营养管理_NutritionSystem | `yushu_12_营养管理_NutritionSystem/SKILL.md` | `#营养`/蛋白质/饮水/补剂 |
| yushu_13_恢复管理_RecoverySystem | `yushu_13_恢复管理_RecoverySystem/SKILL.md` | `#恢复`/睡眠/酸痛/压力 |
| yushu_14_身体分析_BodyAnalytics | `yushu_14_身体分析_BodyAnalytics/SKILL.md` | `#体测`/趋势/Body Score |
| yushu_多Agent协作 | user-level skill（yushu_multi-agent-collaboration） | 多Agent同步 |
| yushu_import-project | user-level skill | 导入新项目 |
