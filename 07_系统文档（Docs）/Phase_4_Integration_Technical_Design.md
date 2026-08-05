# Phase 4 Integration Technical Design

日期：2026-08-05
设计原则：Markdown First / Local First / Human Approval / Gateway First / Agent Runtime 统一管理

## Obsidian Integration

### 目标

Human Knowledge Interface。

### Vault连接方式

Obsidian 不作为 Agent 的直连资源，而是通过知识库网关连接到 Vault。

建议链路：

```text
Obsidian
↓
Knowledge Vault
↓
Gateway
↓
Agent Runtime
```

连接重点不是“接管 Obsidian”，而是把 Obsidian 保持为人类编辑入口。

### Community Plugin评估

优先评估社区插件，判断它们是否已经满足：

- Markdown 编辑
- 本地文件同步
- 差异预览
- 只读/受控写入
- 与 Gateway 协作

如果现成插件能满足约束，就优先使用；只有在无法满足隔离要求时，才考虑额外开发轻量适配层。

### AI辅助编辑流程

推荐流程：

```text
Agent Proposal
↓
Human Review
↓
Approval
↓
Gateway Update
↓
Markdown Write
```

AI 只提供建议、差异和解释，不直接替代人类编辑。

### Markdown保护机制

必须保留：

- 文件级别保护
- 路径级别白名单
- 差异预览
- 审批日志
- 可回滚记录

禁止：

- Agent 直接写 Vault
- Agent 绕过差异审查
- 默认自动同步外部数据

## llm_wiki Integration

### 目标

Knowledge Reader / Search / MCP Provider。

### Runtime连接方式

llm_wiki 作为读侧能力接入，连接链路应为：

```text
Agent Runtime
↓
Gateway
↓
llm_wiki
↓
Vault
```

### Gateway调用流程

Runtime 统一发起查询，Gateway 负责：

- 身份校验
- 权限判定
- 资源裁剪
- 结果返回

llm_wiki 只负责读与检索，不承担 Agent 决策。

### 权限控制

默认权限应当是：

- 只读
- 搜索优先
- 受控上下文返回

任何写入类需求都必须回到 Proposal / Approval 流程。

### 禁止修改exe

`llm_wiki.exe` 必须保持不改动。

设计上只允许：

- 外围适配
- Gateway 对接
- 调用封装

不允许直接改可执行文件本体。

## Feishu Integration

### 目标

Execution OS Interface。

### Task Proposal

Feishu 的进入点应该是已批准的任务提案，而不是 Agent 的直接执行输出。

推荐链路：

```text
Agent Proposal
↓
Approval
↓
Feishu
↓
Human Decision
```

### Approval Workflow

任务提案进入 Feishu 前，需要明确审批结果：

- 通过
- 拒绝
- 过期

只有通过的提案才能进入通知或任务创建阶段。

### Notification机制

通知用于：

- 提醒审批
- 提醒执行
- 提醒状态变化
- 提醒人工回看

通知本身不能成为绕过审批的通道。

## Phase 4设计约束

必须继续保持：

- Markdown First
- Local First
- Human Approval
- Gateway First
- Agent Runtime 统一管理

禁止：

- 直接连接 Vault
- 自动同步外部数据
- 默认联网
- 绕过审批

Phase 4 的工作目标是把外部系统纳入 Runtime 治理边界，而不是把治理边界拆掉。
