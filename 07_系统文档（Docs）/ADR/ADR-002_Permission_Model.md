# ADR-002 Permission Model

Date: 2026-08-05
Status: Accepted
Scope: Runtime Permission / Agent Governance

## 决策

Runtime 采用基于 `AgentDefinition.permissions` 的最小权限字符串模型。所有关键行为在 RuntimeKernel 或内部服务中调用 `PermissionManager.require()` 进行门控。

## 为什么这样设计

Phase 2 的目标是建立安全、可测试、可解释的 Runtime 内核。字符串权限模型足够明确、简单、可测试，能覆盖 Phase 3 Agent 的核心边界：

- `execute`
- `read_knowledge`
- `propose_change`
- `request_access`
- `use_tools`

权限不是永久拥有的广义身份特权，而是 Agent 执行某类操作所需的最小能力声明。

## 为什么不采用其他方案

### 不采用 OS 文件权限作为主权限系统

Personal Knowledge OS 的风险边界不是单纯文件读写，而是知识语义、敏感等级、Agent 身份、审批流程和审计。OS 权限无法表达这些治理规则。

### 不采用复杂 RBAC / ABAC DSL

Phase 2 当前需要稳定内核，不需要过早引入复杂策略语言。复杂 DSL 会增加调试成本，也可能掩盖真实权限路径。

### 不采用“Agent 自律”

仅靠 prompt 或 Agent 自我约束不可审计，也不可证明。

## 优点

- 实现简单。
- 测试清晰。
- 易于代码审查。
- 与 `AgentDefinition` 绑定，便于 Phase 3 注册审查。
- 与 Tool Manager、Context Manager、Approval Engine 可组合。

## 缺点

- 目前表达能力有限。
- 尚未支持资源级策略 DSL。
- 无法单独表达时间、环境、风险评分等动态条件。
- 权限字符串需要保持命名纪律。

## 未来如何演化

- 保持当前字符串权限作为基础层。
- 在 Gateway / Policy 层增加 folder、metadata、agent policy 三层过滤。
- 未来可以引入策略 DSL，但必须向后兼容现有权限。
- 高敏数据继续通过 Access Request 与 Human Approval 补足动态授权。
