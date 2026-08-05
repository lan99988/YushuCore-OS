# ADR-003 Context Manager

Date: 2026-08-05
Status: Accepted
Scope: Runtime Context / Knowledge Boundary

## 决策

Runtime 使用 Context Manager 通过 KnowledgeGatewayClient 构建 `RuntimeContext`。Agent Handler 只能接收 RuntimeContext，不接收 Vault 文件路径。

## 为什么这样设计

Knowledge Vault 是长期事实源。Agent 如果直接打开 Markdown，就会绕过权限、敏感度过滤、审计和人工审批。Context Manager 把知识访问收敛为受控上下文：

```text
Agent -> RuntimeKernel -> ContextManager -> KnowledgeGatewayClient -> Knowledge Gateway -> Vault
```

这样 Agent 只能看到已授权的 `knowledge`、`experience`、`principles` 节点，而不是整个文件系统。

## 为什么不采用其他方案

### 不让 Agent 直接访问 Obsidian/Vault 文件

Obsidian 是人工编辑入口，不是 Agent API。直接访问会破坏 Human Approval。

### 不让 llm_wiki 成为事实源

llm_wiki 的定位是 reader / search / MCP provider，不是知识事实源，也不应替代 Gateway。

### 不把上下文构建放到 Agent 内部

Agent 内部构建上下文会导致每个 Agent 自己实现权限过滤，难以一致审计。

## 优点

- 明确 Gateway Boundary。
- 不暴露 Vault 路径。
- 可统一插入权限检查。
- 支持高敏 Access Request。
- 支持 Model Router 根据上下文敏感度决策。

## 缺点

- Agent 灵活性降低。
- Context schema 变化需要谨慎管理。
- Gateway Client 当前仍是轻量适配层，复杂查询能力有待扩展。

## 未来如何演化

- 增加更丰富的 `GatewayNode` metadata。
- 增加 context compression，但不得记录敏感正文到审计日志。
- 增加多轮任务上下文，但长期沉淀仍必须走 Proposal。
- 高敏上下文继续保持一次性授权语义。
