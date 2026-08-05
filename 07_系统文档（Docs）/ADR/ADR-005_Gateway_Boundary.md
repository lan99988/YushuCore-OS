# ADR-005 Gateway Boundary

Date: 2026-08-05
Status: Accepted
Scope: Knowledge Gateway / Runtime Boundary

## 决策

Runtime 通过 `KnowledgeGatewayClient` 与 Knowledge Gateway 通信。Agent 不直接访问 Vault，不直接修改 Markdown，不直接调用 llm_wiki 或外部知识 API。

## 为什么这样设计

Knowledge Gateway 是 Vault 与 Agent 之间的安全边界。它负责权限过滤、上下文生成、Proposal 写入路径和未来多 Agent 扩展。Runtime 管理执行，Gateway 管理知识边界，两者职责分离。

标准路径：

```text
Agent
-> RuntimeKernel
-> PermissionManager
-> KnowledgeGatewayClient
-> Knowledge Gateway
-> Vault
```

## 为什么不采用其他方案

### 不让 Agent 直接访问 Vault

这会破坏 Markdown First 的治理模型，使知识修改不可审计、不可审批、不可回滚。

### 不让 llm_wiki 作为 Gateway 替代品

llm_wiki 是阅读、搜索、MCP Provider，不是安全治理边界，也不应修改 `llm_wiki.exe`。

### 不把 Gateway 逻辑塞进 Runtime

Runtime 负责 Agent 执行内核，Gateway 负责知识访问边界。混合两者会让系统难以演化。

## 优点

- 知识访问路径统一。
- Vault 不暴露给 Agent。
- 未来可以替换 Gateway 实现而不破坏 Agent。
- Proposal / Approval 有明确落点。
- 与 Obsidian、llm_wiki、Feishu 的职责边界清晰。

## 缺点

- Gateway 能力不足时，Agent 能力会受限。
- Runtime 与 Gateway 的契约需要持续维护。
- Phase 3 需要避免为了方便而绕过 Gateway。

## 未来如何演化

- Gateway 增加 query、context、proposal、approval、index 能力。
- Gateway 可接入 llm_wiki 作为 reader/search provider，但不把 llm_wiki 变成事实源。
- Gateway 可接入 Obsidian 工作流，但仍由 Human Owner 审核知识变化。
- Gateway API 变化必须保持 Runtime Client 兼容或走迁移流程。
