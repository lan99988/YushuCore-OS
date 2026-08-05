# ADR-001 Runtime Architecture

Date: 2026-08-05
Status: Accepted
Scope: Personal Knowledge OS / Personal Agent Runtime

## 决策

Personal Knowledge OS 采用 `runtime_core` 作为 Personal Agent Runtime 的本地执行内核。所有 Agent 必须经 Runtime 注册、激活、执行、权限检查、上下文构建、工具调用、审批和审计。

## 为什么这样设计

系统的核心风险不是“Agent 不够聪明”，而是 Agent 绕过治理边界直接读写长期知识资产。Runtime Core 作为统一入口，可以把 Agent 生命周期、权限、模型路由、工具调用、Proposal 和日志审计集中在一个可验证的内核中。

该设计符合冻结架构中的要求：

- 所有 Agent 必须经过 Personal Agent Runtime。
- Agent 禁止直接访问文件。
- Agent 禁止直接调用外部 API。
- 关键行为必须可审计。
- Human Approval 是安全边界。

## 为什么不采用其他方案

### 不采用“Agent 自带权限与工具”

如果每个 Agent 自行管理权限、工具和日志，系统会很快变成多个小黑箱，难以审计，也难以证明没有绕过 Gateway。

### 不采用“直接由 Agent 读写 Vault”

Vault 是长期事实源。直接读写会让权限、审计、回滚和人工审批都失效。

### 不采用“一开始做复杂分布式 Runtime”

当前运行环境是 Windows 11、无 Docker、无 WSL2。本地优先和可维护性比过早分布式化更重要。

## 优点

- 单一执行入口，便于审计。
- Agent 生命周期清晰。
- 权限和上下文边界集中。
- 可通过测试证明关键路径。
- 适合 Windows Native 本地环境。
- Phase 3 Agent 可以在稳定契约上扩展。

## 缺点

- Runtime Core 会成为架构关键路径。
- 进程内 Event Bus 不适合跨进程 Agent。
- 当前不是远程服务，暂不适合多设备协同执行。
- Runtime API 冻结后，后续修改成本更高。

## 未来如何演化

- 保持 `runtime_core` API 稳定。
- 在 Agent 层增加 SDK，而不是改 Runtime 内核。
- 未来如果需要服务化，应新增 Runtime Server Adapter，不直接破坏现有 API。
- Event Bus 可扩展到外部消费者或 Dashboard。
- Runtime API 变更必须走 `Proposal -> Review -> Approval -> Migration`。
