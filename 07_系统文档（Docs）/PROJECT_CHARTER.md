# Yushu-OS 项目章程

> 状态：Accepted
> 生效日期：2026-09-26
> 决策依据：ADR-010

## 1. 使命

Yushu-OS 是一个长期理解用户目标、状态、约束、知识和历史，并协助规划、执行、调整与复盘的个人自适应 AI 操作系统。

系统服务的对象是用户本人及其希望达到的更好状态，而不是某一张任务表、某一个知识库或某一种自动化工具。

最高设计原则：消除模糊，并降低用户的维护阻力。

~~~text
信息 → 理解 → 关系 → 判断 → 决策 → 行动 → 结果 → 学习
~~~

## 2. 用户价值

用户只面对六条逻辑链：

| 逻辑链 | 用户问题 | 系统结果 |
|---|---|---|
| Capture | 发生了一件事 | 理解、归档、提取行动 |
| Plan | 我要实现一个目标 | 目标、差距、项目、里程碑与计划 |
| Today | 我今天应该怎么过 | 硬约束、建议安排、待确认变化 |
| Adjust | 情况发生变化 | 影响分析、重算、执行或请求确认 |
| Review | 最近怎么样 | 结果、趋势、原因假设与下一周期 |
| Explore | 帮我理解一个问题 | 证据、解释、置信度与建议 |

用户不需要知道后台调用了哪个插件，也不应被要求先选择模块再表达需求。

## 3. 范围

核心执行领域包括 Goal、Project、Task、Calendar、Learning、Knowledge 和 Body。

个人领域包括 Social、Finance、Life Administration、Creation、Interest 和 Experience。

核心治理包括 Identity、Context、Constraint、Permission、Decision、Personal Intelligence、Audit 和 Plugin Registry。

## 4. 非目标

- 不建设要求用户持续填表的全功能人生数据库。
- 不建设逐笔财务账本、投资或资产管理系统。
- 不维护高字段数量的联系人档案。
- 不预建尚未进入用户生活的行政领域。
- 不把兴趣 KPI 化。
- 不训练会自动改写用户人格或价值观的模型。
- 不允许 Agent 绕过 Runtime、Knowledge Gateway 或外部写入闸门。
- 本阶段不建设 Web GUI；交互面保持对话、API 和现有移动触达。
