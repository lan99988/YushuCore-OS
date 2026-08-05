# Phase 4 Integration Technical Design Review

日期：2026-08-05
前置状态：Phase 3.5 Agent Implementation = Accepted
Git Tag：`phase3.5-agent-accepted-v1.0`
Architecture Direction：Accepted
实现状态：Phase 4 contract and adapter implementation verified
本轮状态：Architecture Accepted / Live External Handshake Pending

本文件现在同时记录审查结论和实现证据。外部系统仍保持 Gateway First；本地测试使用注入式 Client，不把真实凭据写入仓库。

## Review结论

当前设计的主架构保持不变：

```text
External Integration
↓
Integration Adapter Layer
↓
Personal Agent Runtime
↓
Knowledge Gateway
↓
Resource
```

审查结论为：

**Phase 4 Architecture Direction: Accepted。**

实现必须继续遵守本文档的 Adapter、Gateway、Approval 和 Network Policy 边界。

## Implementation Status

当前已实现：

- `runtime_core.models.AgentRequest / AgentResult / AutonomyLevel`
- `RuntimeKernel.execute_request()`
- `runtime_core.integration_policy.IntegrationPolicy`
- `runtime_core.collaboration.AgentEventRelay`
- `runtime_core.permissions.AgentPermissionMatrix`
- `integrations.obsidian.ObsidianAdapter`
- `integrations.llm_wiki.LlmWikiAdapter`
- `integrations.feishu.FeishuAdapter`
- Knowledge Importer / Reviewer / Knowledge Auditor
- Phase 4 Skill Catalog
- Health / Research / File / Calendar / Communication Future Agent 安全骨架
- Agent Memory 按 Agent 逻辑分区

当前验证：

```text
Phase 4 focused tests: 25 passed
Full test suite: 196 passed, 47 subtests passed
compileall: passed
Boundary violations: 0
git diff --check: passed
```

真实 Obsidian、llm_wiki、Feishu 服务握手仍需要外部运行环境和凭据；在此之前，Adapter 只允许离线、注入式和只读测试。

### 子阶段状态

| 子阶段 | 状态 | 证据 |
|---|---|---|
| Phase 4.1 Obsidian Integration | Contract Implemented | `integrations.obsidian.ObsidianAdapter`、Proposal / Gateway boundary tests |
| Phase 4.2 llm_wiki Integration | Contract Implemented | `integrations.llm_wiki.LlmWikiAdapter`、`LlmWikiApiClient`、路径与只读测试 |
| Phase 4.3 Feishu Integration | Contract Implemented | `integrations.feishu.FeishuAdapter`、Approval / Idempotency tests |
| Phase 4.4 Integration Security Hardening | Verified | OFF / ASSIST / SYNC、EventBus、Permission Matrix、Boundary = 0 |

### 强制边界

任何外部系统都不能直接访问：

- Knowledge Vault
- Agent Memory
- Personal Memory
- Runtime Core

外部系统只能通过 Integration Adapter Layer 进入 Runtime 的受控入口；Adapter 不拥有 Vault 路径、Memory 路径或 Runtime 内部对象的直接引用。

## 1. Integration Layer架构审查

### 目标分层

```text
External System
  └─ Obsidian / llm_wiki / Feishu
        ↓
Integration Adapter
  └─ 协议转换、鉴权、超时、幂等、错误归一化
        ↓
Personal Agent Runtime
  └─ Agent 生命周期、网络模式、模型路由、审计
        ↓
Knowledge Gateway / Execution Gateway
  └─ 资源访问与变更审批
        ↓
Resource
  └─ Markdown Vault / llm_wiki reader / Feishu task system
```

### 审查判断

| 审查项 | 结论 |
|---|---|
| 外部系统是否先进入 Adapter | 必须 |
| Adapter 是否能直接读写 Vault | 禁止 |
| Adapter 是否能访问 Agent Memory | 禁止 |
| Adapter 是否能访问 Personal Memory | 禁止 |
| Adapter 是否能导入 Runtime Core 对象 | 禁止 |
| 所有资源访问是否经过 Gateway | 必须 |
| 所有变更是否经过 Proposal / Approval | 必须 |
| 所有调用是否具备 correlation id 和 Audit 记录 | 必须 |

Adapter 的职责只包括协议适配和失败归一化，不承担业务决策，不复制 Agent SDK，不绕开 Runtime。

## 2. Obsidian Integration Review

### 定位确认

Obsidian 定位为：

**Human Knowledge Interface**

Obsidian 不是：

- Knowledge Database
- Agent Runtime
- Automation Engine

### 数据流

```text
Human
↓
Obsidian
↓
Markdown Vault
↓
Knowledge Gateway
↓
Personal Agent Runtime
```

Agent 需要编辑知识时，流程反向经过 Proposal：

```text
Agent Proposal
↓
Human Review
↓
Approval
↓
Knowledge Gateway
↓
Markdown Vault
↓
Obsidian Refresh
```

### 设计检查

| 检查项 | 审查结论 |
|---|---|
| Markdown First | 保持。Markdown 仍是主数据载体 |
| YAML Schema | 保持。AI 编辑不得删除或重命名受保护字段 |
| Git 管理 | 保持。所有批准后的 Markdown 变更都是可 diff、可提交、可回滚的文件变更 |
| 云端依赖 | 默认不引入。网络模式为 `OFF` 时仍可使用本地 Obsidian |
| 社区插件替代方案 | 必须先评估，再决定是否自研 |

### Community Plugin评估门槛

在开发自研插件前，必须形成逐项评估记录：

- 是否支持本地 Markdown
- 是否能保留 YAML frontmatter
- 是否支持差异预览
- 是否允许只读或受控写入
- 是否会自动联网或上传内容
- 是否能在 Gateway / Git 约束下工作

只有当现有社区方案无法同时满足“本地、可审查、保留 Schema、可回滚、无默认联网”时，才允许提出自研插件 Proposal。自研插件必须隔离在 Adapter 层，不能把 Vault 访问权下放给 Agent。

## 3. llm_wiki Integration Review

### 定位确认

llm_wiki 定位为：

- Knowledge Reader
- Search Interface
- MCP Provider

它不是新的知识源，也不负责知识写入。

### 数据流

```text
Agent Runtime
↓
Knowledge Gateway
↓
llm_wiki
↓
Vault
```

### 调用方式

Phase 4.2 只设计受控读接口，建议最小接口集：

- `knowledge.search`
- `knowledge.read_context`
- `knowledge.get_schema`
- `knowledge.health`

每次调用至少携带：

- `agent_id`
- `task`
- `credential`
- `network_mode`
- `correlation_id`
- `requested_scope`

Adapter 负责把 llm_wiki 的输出转换成 Runtime 可识别的 Gateway 响应，不能把原始进程对象、文件句柄或 Vault 路径暴露给 Agent。

### 权限模型

- 默认只读
- 只允许 `read_knowledge`
- 按 Agent domain、resource scope 和 sensitivity 过滤
- 禁止访问 Agent Memory、Personal Memory 和 Runtime state
- 任何写入意图都必须被拒绝并记录

### MCP接口设计

MCP 暴露的是“知识读取能力”，不是“文件操作能力”：

```text
knowledge.search(query, scope, limit)
knowledge.read_context(task, scope, max_sensitivity)
knowledge.get_schema(node_id)
knowledge.health()
```

禁止提供：

- `write_file`
- `delete_note`
- `rename_note`
- `execute_command`
- 任意 Vault path 操作

### 错误处理

必须区分并审计：

- Gateway 拒绝
- 权限不足
- llm_wiki 不可用
- 调用超时
- 返回格式错误
- 索引陈旧

读请求可以在明确上限内重试；写请求在本层不存在。任何失败都应 fail closed，不得降级为直接读 Vault。

### 强制禁止

- 禁止修改 `llm_wiki.exe`
- 禁止绕过 Gateway
- 禁止让 llm_wiki 成为新的知识源
- 禁止自动写入知识

## 4. Feishu Integration Review

### 定位确认

Feishu 定位为：

**Execution OS Interface**

负责：

- Task
- Project
- Approval
- Notification

Feishu 禁止保存知识正文；知识正文仍归 Markdown Vault 和 Knowledge Gateway 管理。

### 流程

```text
Agent
↓
Proposal
↓
Approval Engine
↓
Feishu
↓
Human Decision
↓
Execution
```

### Approval数据结构

```yaml
proposal_id:
agent_id:
target_type:
title:
details:
evidence:
confidence:
risk:
status:
requested_at:
expires_at:
reviewer:
reviewed_at:
decision_reason:
correlation_id:
idempotency_key:
```

推荐状态：

```text
draft
→ pending_human_review
→ approved | rejected | expired
→ submitted
→ executed | failed
```

### Task Proposal结构

```yaml
proposal_type: task
title:
description:
project_id:
assignee:
due_at:
evidence:
execution_gateway: feishu
requires_human_review: true
status: pending_human_review
executed: false
```

Proposal 中只保存执行所需的最小任务字段和证据引用，不嵌入知识正文。

### 权限边界

- Agent 只能创建 Proposal
- Approval Engine 才能改变审批状态
- Feishu Adapter 只能提交已批准 Proposal
- Feishu 不得回写知识正文
- Notification 不能改变审批结果
- 所有外部写操作必须带 `idempotency_key`

### 失败恢复机制

- Feishu 不可用：Proposal 保持 `approved`，不丢失，不自动降级为本地执行
- 请求超时：根据 `idempotency_key` 查询结果，禁止盲目重复创建任务
- 部分成功：记录外部 task id，转入 `failed` 或 `submitted`，等待人工处理
- 审批过期：禁止提交，生成审计事件
- 人工拒绝：记录原因，不自动重试
- 需要撤销：通过新的 Proposal 走补偿动作，而不是直接修改旧审计记录

## 5. Network Governance Review

默认网络模式：

```text
OFF
```

### OFF

允许：

- 本地 Runtime
- 本地 Gateway
- 本地 Markdown Vault
- 本地受控 Tool
- 本地 llm_wiki 进程适配

禁止：

- 外部 HTTP / HTTPS
- 云模型调用
- Feishu API
- 后台同步
- 未经批准的外部数据读取

### ASSIST

允许：

- 由 Human 触发的单次外部查询
- 经过 allowlist 的只读外部 API
- 结果进入临时上下文或 Inbox

禁止：

- 后台自动同步
- 自动写入知识
- 自动创建 Feishu 任务
- 通过外部结果绕过审批

每次 ASSIST 调用都必须记录 Agent、资源、用途、时间、结果摘要和 correlation id。

### SYNC

SYNC 只允许在显式启用的同步任务中运行，且必须满足：

```text
External Data
↓
Inbox
↓
Review
↓
Knowledge
```

保证方式：

- 外部数据永远先进入 Inbox
- 同步任务使用固定 allowlist
- 原始内容保留 source 和 digest
- Analyzer / Librarian 先生成建议
- Human Review 通过后才能进入正式 Knowledge
- 同步失败不会覆盖已有知识

## 6. Security Review

Phase 4 继续遵守：

- Gateway First
- Human Approval
- Local First
- Markdown First

### Integration Security Checklist

| 项目 | 状态 |
|---|---|
| 外部系统是否绕过 Gateway | 禁止；设计通过，需 Phase 4 Boundary Test |
| 是否存在自动写入 | 禁止；Obsidian / llm_wiki / Feishu 均无默认自动写入 |
| 是否需要审批 | 所有知识写入和外部执行都需要 |
| 是否支持审计 | 支持；Adapter 调用必须继承 Runtime correlation id |
| 是否可回滚 | 必须支持；Markdown 依靠 Git，Feishu 依靠幂等与补偿 Proposal，llm_wiki 保持只读 |

### 安全不变量

- 外部系统不能直接获得 Vault path
- Adapter 不能直接读写 Memory
- 任何写入动作都必须存在 Proposal id
- 任何批准动作都必须存在 reviewer 和时间戳
- 任何外部提交都必须可由 correlation id 追溯
- 失败时默认拒绝，不默认放行

## 7. Phase 4 Risk Register

| 风险 | 风险描述 | 影响 | 当前防护 | 解决方案 |
|---|---|---|---|---|
| Obsidian 插件导致数据结构污染 | 插件改写 frontmatter、路径或 Markdown 结构 | 知识解析失败、Git diff 噪声、历史数据不可读 | Markdown First、YAML Schema、Git diff | 先做社区插件评估；写入前 Schema 校验、diff 预览、失败回滚 |
| llm_wiki 越权访问 | Reader 或 MCP 暴露底层文件能力 | Agent 读取不应访问的知识或内部状态 | Gateway First、只读权限、禁止文件工具 | 只暴露 search/read_context/schema/health；做 Boundary Test 和 sensitivity Test |
| Feishu 自动执行风险 | 未审批 Proposal 被提交为任务或通知 | 外部系统产生未经授权的行动 | Approval Engine、pending_human_review | Adapter 只接受 approved 状态；幂等键、审批过期和拒绝测试 |
| 网络模式失控 | ASSIST/SYNC 被误用为默认联网 | 隐私泄露、不可控同步、成本增加 | 默认 OFF、Runtime 统一路由 | 策略白名单、模式切换审计、SYNC 专用任务、断网回归测试 |
| 外部 API 依赖 | Feishu、llm_wiki 或插件不可用 | 集成流程中断、重试放大 | Adapter 隔离、错误归一化 | 超时、限次重试、熔断、离线队列、人工恢复和幂等提交 |

## 8. Phase 4 Implementation Plan

本计划只有在本 Review 获得 Human Approval 后才能进入 Implementation。

### Phase 4.1 Obsidian Integration

Design：

- 完成社区插件评估矩阵
- 冻结 Obsidian ↔ Vault ↔ Gateway 数据流
- 定义 YAML 保护字段和 Git 回滚策略

Implementation：

- 只实现 Gateway 适配和最小编辑入口
- 不把 Vault 访问权交给 Agent

Test：

- Markdown/YAML 保真测试
- Git diff 与回滚测试
- 插件无云依赖测试
- Proposal / Approval / Reject 流程测试

Acceptance：

- Human Knowledge Interface 定位成立
- 无直接 Vault 访问
- 无默认自动同步

### Phase 4.2 llm_wiki Integration

Design：

- 冻结最小 MCP 读接口
- 冻结权限、敏感度和错误模型
- 确认 `llm_wiki.exe` 作为不可修改外部依赖

Implementation：

- 实现 Runtime → Gateway → Adapter → llm_wiki 的读链路
- 不实现写知识能力

Test：

- MCP schema 测试
- 越权和敏感度测试
- 超时、不可用、脏响应测试
- 禁止直接读 Vault 的 Boundary Test

Acceptance：

- 只读 Knowledge Reader 可用
- Gateway violations = 0
- llm_wiki.exe 未被修改

### Phase 4.3 Feishu Integration

Design：

- 冻结 Approval、Task Proposal、Notification 数据结构
- 冻结状态机、幂等键和失败恢复规则

Implementation：

- 只实现已批准 Proposal 的 Feishu Adapter
- 不保存知识正文

Test：

- 未审批拒绝测试
- 重复提交幂等测试
- 超时和部分成功恢复测试
- reject / expire / compensate 测试

Acceptance：

- Agent 不能直连 Feishu
- 只有 approved Proposal 能提交
- 外部任务状态可审计、可恢复

### Phase 4.4 Integration Security Hardening

Design：

- 冻结 Adapter 契约
- 冻结 Network Policy
- 冻结 Audit 字段和回滚策略

Implementation：

- 增加 Boundary Validator、策略检查和故障隔离
- 增加离线模式和人工恢复工具

Test：

- OFF / ASSIST / SYNC 三态测试
- 外部系统绕过 Gateway 测试
- 自动写入探测测试
- 审计完整性与回滚演练

Acceptance：

- Integration Security Checklist 全部通过
- Phase 4 四个子阶段均有验收证据
- 未经批准不得进入下一阶段

## Implementation Gate

在收到 Human Design Review 通过信号前：

- 不修改 Agent SDK
- 不修改 Runtime API
- 不修改 Permission Contract
- 不修改 Memory Contract
- 不连接 Obsidian、llm_wiki、Feishu
- 不启动默认联网

审查通过后的正式顺序仍然是：

```text
Design
↓
Implementation
↓
Test
↓
Acceptance
```

## 待审决策

以下事项需要 Human Design Review 明确：

- 社区 Obsidian 插件评估结果及是否需要自研 Adapter
- llm_wiki 的本地调用传输方式
- Feishu 的认证凭据存储方式
- ASSIST / SYNC 的启用审批人和策略文件位置
- Phase 4.1 到 4.4 的验收责任边界
