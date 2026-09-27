# Yushu-OS 架构 V2

> 状态：Accepted
> 生效日期：2026-09-26
> 关联：ADR-001、ADR-002、ADR-003、ADR-006、ADR-008、ADR-009、ADR-010

## 1. 总体架构

~~~text
Experience Layer
Capture / Plan / Today / Adjust / Review / Explore
        ↓
Cognitive Core
Identity / Goal / Context / Constraint / Permission / Decision / Audit
        ↓
Orchestration Layer
Intent Router / Flow Registry / Capability Planner / Policy Check / Executor
        ↓
Capability Plugin Layer
Task / Calendar / Project / Learning / Body / Social / Finance / ...
        ↓
Data / Integration Layer
Feishu / Knowledge Gateway / information_system / Garmin / IMA / Files
~~~

依赖只能自上而下，上层只能调用下层公开接口。下层不得调用上层；编排层不得直接访问具体事实源。

## 2. 与现有代码的映射

| 架构层 | 当前复用位置 | 新增位置 |
|---|---|---|
| Experience Layer | WorkBuddy、现有输入入口 | experience_layer |
| Cognitive Core | runtime_core.context / permissions / approval、cognitive_system、personal_intelligence | 只补缺失合同 |
| Orchestration Layer | runtime_core.kernel / router / scheduler | orchestration |
| Capability Plugin Layer | handlers、agents、integrations 的现有能力 | capability_plugins 适配层 |
| Data / Integration Layer | information_system、knowledge_system、integrations、飞书引擎 | 不新建平行事实源 |

禁止新建第二套 Runtime、第二套 Knowledge Gateway、第二套 information_system 数据库或新的飞书裸写入口。

概念层不与 Python 包一一对应。runtime_core 是现有基础包：context、permissions、approval API 归入 Cognitive Core；kernel、router、scheduler API 为 Orchestration Layer 提供受控执行服务。新 orchestration 只能调用这些公开 API，不得反向被 Cognitive Core 引用。

## 3. 联邦式事实源

系统采用联邦式事实源，不要求所有数据存入一个数据库。

| 数据类型 | 权威事实源 | 访问边界 |
|---|---|---|
| 任务、日历、项目执行态、承诺和移动端触达状态 | 飞书 | 经现有 Processor 或 Integration |
| 知识正文、经验、方法和原则 | D:\Knowledge | 经 Knowledge Gateway |
| 认知资产投影 | IMA + 飞书双持久化 | 经 cognitive_system，遵循 ADR-009 |
| 信息对象、识别状态、领域观察 | information_system SQLite | 经 Information Plugin |
| 身体原始数据 | Garmin / Body Dataset | 经 Body Plugin |
| 系统配置、插件清单 | Git 版本化本地文件 | Runtime 加载 |
| 财务 | 月度快照 | Finance Plugin，经批准写入 |

IMA 是信息正文来源和捕获入口，不是业务数据库，也不是知识事实源。

ADR-009 的 IMA + 飞书双持久化继续用于认知资产投影、同步状态和跨系统检索，不构成第二份知识正文权威。D:\Knowledge 负责人工可读的长期知识正文；cognitive_system 负责可重建的结构化认知资产及其双通道持久化。两者冲突时不得静默覆盖。

## 4. 核心边界

### Runtime Boundary

Agent 的执行、权限、工具、审批和审计继续通过 runtime_core。现有 AgentDefinition.autonomy_level 上限保持 Level 2。

### Knowledge Boundary

Agent 不接收 Vault 路径。所有知识读取经 Context Manager 和 Knowledge Gateway；所有长期知识写入经 Proposal → Review → Approval → Write。

### External Boundary

全局 network_mode 保持 OFF。具名集成例外必须显式启用，并继续服从审批策略。

### Plugin Boundary

插件只描述和提供能力，不决定跨领域优先级。插件不能绕过 Runtime、Action Policy 或事实源适配器。

## 5. 请求数据流

~~~text
User Input
  → Experience Request
  → Intent Router
  → Flow Selection
  → Capability Plan
  → Plugin Registry Resolution
  → Action Policy
  → Runtime Execution / Approval
  → Result Aggregation
  → User-facing Explanation
  → Audit
~~~

任何有副作用的 Capability Call 都必须在执行前产生 Policy Decision。

## 6. 错误与部分失败

- 缺少能力：返回 capability_gap，不静默假装完成。
- 插件休眠：返回 dormant，并说明激活条件。
- 权限拒绝：返回 blocked_by_policy，并给出 reason_code。
- 需要审批：返回 approval_required，不执行副作用。
- 部分失败：状态必须是 partial，并列出已完成、未执行和补偿动作。
- 外部系统不可用：保留本地计划和审计，禁止重复写入。

## 7. 迁移方式

采用 Strangler Migration：

1. 新接口先以适配器包装现有实现。
2. 新旧路径运行行为等价测试。
3. 新路径先进入 shadow 或 dry-run。
4. 两个连续验收周期稳定后才讨论删除旧入口。
5. 删除旧入口必须由用户确认并使用独立计划。

input_parser_old.py、现有 handler、daily_scheduler 和 Body OS 契约在本轮不删除。

## 8. 安全不变量

- network_mode 默认 OFF。
- Agent 自治等级不超过 Level 2。
- 外部承诺、支付、消息发送、固定会议变化和不可逆删除必须审批。
- 审计不记录知识正文、凭证、财务截图正文或健康原始数据。
- 未批准的 Personal Rule Candidate 不进入正式决策规则。
