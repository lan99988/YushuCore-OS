# Phase 2 Runtime 验收决策记录

Version: v1.0
Date: 2026-08-05
Scope: Personal Knowledge OS / Personal Agent Runtime
Status: Accepted

## 1. 决策结论

```text
Decision: closeout accepted
Accepted by: Human Owner
Accepted at: 2026-08-05
Approval source: Codex thread user instruction
```

Human Owner 已明确批准：

```text
接受 Phase 2 Runtime 收口。
批准进入 Phase 3（Agent Implementation）。
```

因此，Phase 2 Runtime Core 从 `closeout candidate` 正式变更为：

```text
Phase 2 Runtime Core: accepted
```

## 2. 决策依据

本次验收基于以下材料：

- [Phase 2 Runtime Closeout Audit](Phase_2_Runtime_Closeout_Audit.md)
- [Phase 2 Runtime Human Acceptance Checklist](Phase_2_Runtime_Human_Acceptance_Checklist.md)
- [Runtime API Contract](Runtime_API_Contract.md)
- [Runtime Core Operation Guide](Runtime_Core_Operation_Guide.md)
- Runtime focused tests 最近验证结果
- 全量测试最近验证结果

## 3. 验收范围

本次 Accepted 的范围仅限：

- `runtime_core/`
- Runtime policy loading
- Agent registration / activation / execution lifecycle
- Permission Manager
- Context Manager
- Memory Manager
- Model Router
- Tool Manager
- Approval Engine
- Access Request Store
- Event Bus
- Runtime Logger
- Knowledge Gateway Client boundary
- Phase 2 Runtime 文档与验收材料

不代表以下内容已经完成：

- Phase 3 Agent Implementation
- Knowledge Agent 实现
- Body Agent 实现
- Study Agent 实现
- Project Agent 实现
- Feishu 审核系统完整接入
- Obsidian 插件或 UI 集成
- 旧笔记迁移

## 4. 冻结规则

从本记录生效起，Runtime API 进入冻结状态。

Phase 3 开发期间禁止：

- 重构 Runtime Core
- 修改 Runtime API
- 改变 Runtime 目录结构
- 引入破坏兼容性的改动
- 让 Agent 绕过 Runtime / Gateway / Tool Manager / Approval Engine

如果确需修改 Runtime 公共接口，必须走：

```text
Proposal -> Review -> Approval -> Migration
```

任何未经过该流程的 Runtime API 破坏性修改均视为架构违规。

## 5. Git 标记

本次验收对应 Git Tag：

```text
phase2-runtime-accepted-v1.0
```

该 tag 用作 Phase 2 Runtime 收口基线。Phase 3 开发应以该 tag 之后的提交作为扩展起点，而不是重新塑造 Runtime Core。

## 6. Phase 3 授权边界

Human Owner 批准进入 Phase 3，但授权边界是：

- 可以设计并实现 Agent 层。
- Agent 必须通过 Runtime 注册、激活、执行。
- Agent 只能通过 RuntimeContext 获取上下文。
- Agent 只能通过 KnowledgeGatewayClient / Knowledge Gateway 访问知识。
- Agent 写入知识必须走 Proposal / Human Approval。
- Agent 调用外部能力必须走 Tool Manager。
- 默认网络模式仍为 `OFF`。
- `level_3` / `level_4` 数据仍禁止上云。

## 7. 审计备注

本记录由 Codex 根据 Human Owner 明确批准更新。它记录人工决策，不代表 Codex 自行批准 Phase 2。
