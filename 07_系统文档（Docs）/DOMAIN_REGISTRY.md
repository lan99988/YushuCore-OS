# Yushu-OS 领域注册表

> 状态：Accepted
> 原则：真实需要驱动激活，避免预建维护负担

## 1. 领域状态

- Dormant：能力存在，但当前生活中没有真实对象。
- Active：存在真实对象，参与捕获、规划、提醒或复盘。
- Archived：对象或领域已经结束，保留历史但不主动参与。

新一级领域必须经过 Observation → Candidate → 用户确认。关键词命中不能直接创建一级领域。

## 2. 核心领域

| 领域 | 目的 | 默认状态 | 记录粒度 |
|---|---|---|---|
| Goal | 长期与阶段目标 | Active | 目标级 |
| Project | 多步骤结果 | Active | 项目级 |
| Task | 明确行动 | Active | 高频、精细 |
| Calendar | 时间资源与硬约束 | Active | 高频、精细 |
| Learning | 学习目标、进度与复习 | Active | 日/周 |
| Knowledge | 长期知识与关系 | Active | 长期沉淀 |
| Body | 训练、营养、恢复与状态 | Active | 每日与趋势 |

## 3. 个人领域

### Social

记录关系事件，而不是维护联系人档案。核心对象仅有 Person、Interaction、Commitment。默认可见字段只有姓名、关系、上次联系、下次关注和未完成承诺。

### Finance

采用月度快照，不保存逐笔流水。每月底由用户上传统计截图，系统提取总收入、总支出、结余、储蓄率、消费结构、大额支出、环比、异常和下月关注。

### Life Administration

采用渐进激活。仅包括证件与身份、住房与设施、个人资产维护、服务与合同、行政手续。未出现真实对象的子领域保持 Dormant，不创建空记录。

### Creation

~~~text
Idea → Draft → Production → Publish → Feedback → Archive
~~~

执行态与长正文分离，正文不在多个事实源双写。

### Interest

Interest 以探索和愉悦为价值，不强制任务化、不设置 KPI、不要求连续打卡。只有用户主动要求产生结果时才转换为 Project。

### Experience

~~~text
Wishlist → Planned → Booked → Experienced → Reflection
~~~

Reflection 经用户确认后才可升格为长期经验或规则候选。

## 4. 激活规则

用户输入出现明确真实对象、激活只创建内部结构、不产生外部副作用且可撤销时，可以自动激活。

新增一级领域、创建外部提醒、扩大敏感数据范围或引入长期服务时必须请求用户确认。

## 5. 事实源分工

| 领域信息 | 事实源 |
|---|---|
| 可执行状态、提醒和外部承诺 | 飞书 |
| 长正文、反思、方法和原则 | Knowledge Gateway |
| 捕获来源、识别投影和领域观察 | information_system |
| 身体原始指标 | Garmin / Body Dataset |
| 财务原始输入 | 用户月度截图；系统只保存月度快照 |

## 6. 低摩擦验收

- Capture 不要求先选领域。
- Social 一次自然语言输入可完成记录。
- Finance 每月只需一次上传。
- Dormant 领域零维护。
- Interest 不出现 KPI。
- 所有自动激活和变化均可解释、可撤销。
