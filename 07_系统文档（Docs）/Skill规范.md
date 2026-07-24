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
| 00 | 系统注册表 | Registry | `01_Skill能力库（Skills）/00_Skill注册中心（Registry）/` |
| 01 | 输入解析引擎 | Router | `01_Skill能力库（Skills）/01_输入解析引擎（Router）/` |
| 02 | 随手录-意图分类 | Router | `01_Skill能力库（Skills）/02_意图分类（Router）/` |
| 03 | 随手录-快速查询 | Router | `01_Skill能力库（Skills）/03_快速查询（Router）/` |
| 04 | 随手录-飞书操作 | Processor | `01_Skill能力库（Skills）/04_飞书操作（Processor）/` |
| 05 | 随手录-问答校准 | Processor | `01_Skill能力库（Skills）/05_问答校准（Processor）/` |
| 06 | 每日排程算法 | Processor | `01_Skill能力库（Skills）/06_每日排程（Processor）/` |
| 07 | 习惯管理系统 | Domain | `01_Skill能力库（Skills）/07_习惯管理系统（Domain-AtomicHabits）/` |
| 08 | 深度工作系统 | Domain | `01_Skill能力库（Skills）/08_深度工作系统（Domain-DeepWork）/` |
| 09 | 比赛管理系统 | Domain | `01_Skill能力库（Skills）/09_比赛管理系统（Domain-Competition）/` |

> 每个 `SKILL.md` 顶部均已按本模板补充「标准信息段」，详见各文件。
