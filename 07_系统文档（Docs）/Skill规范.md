# Skill 标准规范（Skill规范）

> 本文件是「个人混合管理系统」所有 Skill 的**唯一模板来源**。
> 以后新增任何 Skill，必须先按本规范定义「标准信息段」，再写实现细节。
> 目标：打开任意 Skill 的 `SKILL.md`，5 分钟知道它负责什么。

---

## 标准模板（所有 Skill 必须遵守）

每个 `SKILL.md` 顶部必须包含以下「标准信息段」：

~~~
# Skill名称

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | |
| 版本 | |
| 状态 | 稳定 / 活跃 / 设计中 |
| 创建时间 | YYYY-MM-DD |
| 负责人 | 甲乙簿 |

## 功能定位

解决什么问题。（一句话说清职责边界，不含实现细节）

## 触发方式

例如：`#任务` `#习惯` / 无前缀自然语言 / 每日 07:00 定时推送

## 输入

接收什么数据。

## 输出

产生什么结果。

## 依赖

- 飞书 Base（哪些表）
- 数据表：...
- 其他 Skill：...

## 数据

使用哪些表（表名 + 表 ID）。

## 权限

- read：...
- write：...
- admin：无

## 调用链

输入 → 本 Skill → Engine / 飞书操作 → 飞书 Base

## 测试

测试方式：...
最后测试时间：YYYY-MM-DD
~~~

> 模板下方的「实现细节」（解析规则、命令模板、边缘情况等）保持各 Skill 原有结构，**不要求改写**。

---

## 落地 Skill 索引（当前 10 个）

| # | Skill | 类别 | 路径 |
|---|-------|------|------|
| 00 | yushu_00_Skill注册中心_Registry | Registry | `01_Skill能力库（Skills）/yushu_00_Skill注册中心_Registry/` |
| 01 | yushu_01_输入解析引擎_Router | Router | `01_Skill能力库（Skills）/yushu_01_输入解析引擎_Router/` |
| 02 | yushu_02_意图分类_Router | Router | `01_Skill能力库（Skills）/yushu_02_意图分类_Router/` |
| 03 | yushu_03_快速查询_Router | Router | `01_Skill能力库（Skills）/yushu_03_快速查询_Router/` |
| 04 | yushu_04_飞书操作_Processor | Processor | `01_Skill能力库（Skills）/yushu_04_飞书操作_Processor/` |
| 05 | yushu_05_问答校准_Processor | Processor | `01_Skill能力库（Skills）/yushu_05_问答校准_Processor/` |
| 06 | yushu_06_每日排程_Processor | Processor | `01_Skill能力库（Skills）/yushu_06_每日排程_Processor/` |
| 07 | yushu_07_习惯管理_AtomicHabits | Domain | `01_Skill能力库（Skills）/yushu_07_习惯管理_AtomicHabits/` |
| 08 | yushu_08_深度工作_DeepWork | Domain | `01_Skill能力库（Skills）/yushu_08_深度工作_DeepWork/` |
| 09 | yushu_09_比赛管理_Competition | Domain | `01_Skill能力库（Skills）/yushu_09_比赛管理_Competition/` |

> 每个 `SKILL.md` 顶部均已按本模板补充「标准信息段」，详见各文件。
