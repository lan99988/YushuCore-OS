# Phase 2 Runtime 收口审计报告

Version: v0.1
Date: 2026-08-05
Scope: Personal Knowledge OS / Personal Agent Runtime
Status: closeout candidate

## 1. 审计结论

Phase 2 Runtime 已达到冻结架构中对 “Personal Agent Runtime” 的核心验收要求：

```text
Runtime可以：
注册Agent
↓
调用Agent
↓
限制权限
↓
记录日志
```

当前 Runtime 不进入 Phase 3 Agent Implementation，不接入 Knowledge Agent / Body Agent / Study Agent / Project Agent，也不修改 `llm_wiki.exe`、旧笔记、BodyOS、StudyOS、Skill 系统或飞书体系。

本报告建议：

- Phase 2 Runtime 可以进入人工收口审核。
- 后续新增能力应优先进入 Phase 3/4 的明确任务，而不是继续扩大 Runtime 内核。
- 若继续加固 Runtime，应只处理明确的安全、审计、权限边界缺口。
- 人工验收应参考 [Phase 2 Runtime 人工验收清单](Phase_2_Runtime_Human_Acceptance_Checklist.md)。
- 最终决定应写入 [Phase 2 Runtime 验收决策记录](Phase_2_Runtime_Acceptance_Decision_Record.md)。

## 2. 架构冻结要求对照

| 冻结要求 | 当前证据 | 状态 |
|---|---|---|
| Runtime Kernel | `runtime_core/kernel.py` | 已实现 |
| Agent Registry | `runtime_core/registry.py`，支持显式注册与 YAML 加载 | 已实现 |
| Agent Scheduler | `runtime_core/scheduler.py`，覆盖 activate / monitor / update / deactivate | 已实现 |
| Permission Manager | `runtime_core/permissions.py`，运行时权限检查 | 已实现 |
| Context Manager | `runtime_core/context.py`，仅经 Gateway Client 构建上下文 | 已实现 |
| Memory Manager | `runtime_core/memory.py`，JSONL 运行记忆 | 已实现 |
| Knowledge Gateway Client | `runtime_core/gateway_client.py`，Runtime 面向 Gateway 的门面 | 已实现 |
| Model Router | `runtime_core/router.py`，本地优先，高敏强制本地 | 已实现 |
| Tool Manager | `runtime_core/tools.py`，工具注册、权限检查、审计 | 已实现 |
| Approval Engine | `runtime_core/approval.py`，Proposal 审核经 Gateway | 已实现 |
| Event Bus | `runtime_core/events.py`，事件发布和订阅 | 已实现 |
| Logger | `runtime_core/logger.py`，写入 `events.jsonl` | 已实现 |
| Runtime Policy | `runtime_core/policy.py`，加载 `config/network.yaml` / `config/model.yaml` / `config/runtime.yaml` | 已实现 |

## 3. 安全边界对照

### 3.1 Agent 必须经过 Runtime

证据：

- Agent 必须先 `register_agent()`。
- Agent 执行前必须 `activate_agent()`。
- `execute()` 会检查生命周期和 `execute` 权限。
- Agent handler 接收的是 `RuntimeContext`，不是 Vault 文件路径。

状态：已满足。

### 3.2 Agent 禁止直接访问 Vault

证据：

- Runtime 上下文由 `ContextManager -> KnowledgeGatewayClient -> KnowledgeGateway` 构建。
- 高敏上下文必须通过 Access Request。
- Knowledge 修改必须通过 Proposal / Approval 工作流。

状态：已满足。

### 3.3 Agent 禁止直接调用外部工具

证据：

- 工具调用必须通过 `context.tools.call()`。
- Tool Manager 对工具权限、未知工具、失败工具调用分别审计。
- 工具参数不写入 `events.jsonl`。

状态：已满足。

### 3.4 Human Approval 是修改边界

证据：

- `request_update()` 只生成 Proposal。
- `approve_change()` 经 `ApprovalEngine -> KnowledgeGatewayClient -> KnowledgeGateway`。
- Runtime 记录 `proposal_requested` / `proposal_approved` / `proposal_rejected` / `proposal_expired` / `proposal_denied`。
- Proposal 审计事件不记录 `old` / `new` / review reason 正文。

状态：已满足。

### 3.5 Network 默认 OFF

证据：

```yaml
network_mode: OFF
```

Runtime policy 默认离线，`ModelRouter` 在 `OFF` 下保持 local-first。

状态：已满足。

### 3.6 高敏数据不上云

证据：

- `level_3` / `level_4` 上下文强制使用本地模型。
- `model_route_selected` 记录 provider / reason / network mode / complexity / max sensitivity，不记录知识正文。

状态：已满足。

## 4. 审计事件覆盖

当前 Runtime 已覆盖以下关键事件：

```text
agent_activated
agent_deactivated
agent_started
agent_retry
agent_failed
agent_completed
agent_monitored
agent_updated

model_route_selected

tool_called
tool_denied
tool_failed

proposal_requested
proposal_approved
proposal_rejected
proposal_expired
proposal_denied

access_request_created
access_request_approved
access_request_rejected
access_request_denied
access_grant_used
access_grant_denied
```

日志脱敏规则：

- Agent 失败只记录 `error_type`。
- Tool 失败只记录 `error_type`。
- Tool 参数不入日志。
- Proposal 的 `old` / `new` / reason 不入日志。
- Monitor / Update 的 detail 值不入日志，只记录字段名。
- Access Request denied 不记录 request reason。
- Model route 不记录知识正文或上下文正文。

状态：核心关键行为已具备可审计性。

## 5. 测试证据

最新验证结果：

```text
348 passed, 3 skipped, 78 subtests passed
```

覆盖面：

- Runtime Core：注册、激活、执行、权限、工具、模型路由、上下文、审计。
- Runtime Policy：配置加载、默认 `OFF`、非法网络模式拒绝。
- Runtime Scheduler：monitor / update / retry。
- Runtime Gateway Client：上下文、Proposal、Access Grant 经 Gateway Client。
- Knowledge Gateway：权限、Proposal、人审、备份、事务恢复。
- Knowledge Schema：Metadata contract。

## 6. 明确不属于 Phase 2 的事项

以下内容不应在 Phase 2 Runtime 收口前被强行塞入 Runtime：

- Knowledge Agent 实现。
- Body Agent / Study Agent / Project Agent 接入。
- Feishu Approval 真正联动。
- Obsidian 插件或模板联动。
- `llm_wiki.exe` 修改。
- 旧笔记迁移。
- Self Model / Cognitive Proposal 实现。
- 移动端、Tailscale、公网访问。

这些属于 Phase 3、Phase 4 或 Phase 5。

## 7. 风险与保留项

### 7.1 需要人工确认

- Runtime 的 API 是否已经足够稳定，可以作为 Phase 3 Agent 的接入契约。
- `agent_updated` 是否未来需要 Human Approval；当前仅作为 scheduler state update，不修改知识资产。
- 是否需要在 Phase 3 前冻结一版 Runtime API 文档。

### 7.2 不建议继续扩大的方向

- 不建议继续向 Runtime 内部加入具体 Agent 行为。
- 不建议把 Feishu / Obsidian / llm_wiki 直接塞进 Runtime。
- 不建议为了未来自治能力提前引入复杂 Sandbox。

## 8. 下一步建议

推荐顺序：

1. 人工审阅本报告。
2. 按 [Phase 2 Runtime 人工验收清单](Phase_2_Runtime_Human_Acceptance_Checklist.md) 做接受 / 要求修改 / 保持候选的决策。
3. 开始 Phase 3 前，审阅并确认 [Runtime API Contract](Runtime_API_Contract.md)。
4. Phase 3 首个 Agent 应从 Knowledge Agent 开始，但只能使用 Runtime / Gateway / Proposal，不得直接访问 Vault。

## 9. 收口判断

当前判断：

```text
Phase 2 Runtime Core: closeout candidate
```

它不是整个 Personal Knowledge OS v1 的完成状态。它只是说明：

```text
Personal Agent Runtime 作为 AI 执行内核，
已经具备进入人工收口审核的工程基础。
```
