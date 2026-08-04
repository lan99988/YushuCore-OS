# Phase 2 Runtime 人工验收清单

Version: v0.1
Date: 2026-08-05
Scope: Personal Knowledge OS / Personal Agent Runtime
Status: awaiting human acceptance

## 1. 验收目的

本文档用于人工判断 Phase 2 Runtime Core 是否可以从：

```text
closeout candidate
```

正式进入：

```text
closeout accepted
```

它不是自动验收结果。最终验收必须由 Human Owner 确认。

## 2. 验收前必须阅读

人工验收前至少阅读：

- [Phase 2 Runtime 收口审计报告](Phase_2_Runtime_Closeout_Audit.md)
- [Runtime API Contract](Runtime_API_Contract.md)
- [Runtime Core Operation Guide](Runtime_Core_Operation_Guide.md)

## 3. 冻结架构符合性

| Check | Evidence | Human Decision |
|---|---|---|
| Runtime 是 Agent 执行内核，而不是具体 Agent 实现 | `runtime_core/`，未创建 Knowledge Agent / Body Agent / Study Agent | pending |
| 所有 Agent 必须经 Runtime 注册、激活、执行 | `RuntimeKernel.register_agent()` / `activate_agent()` / `execute()` | pending |
| Runtime 包含 Registry / Scheduler / Permission / Context / Memory / Model / Tool / Approval / Event / Logger | `runtime_core/*.py` | pending |
| Runtime 不替代 Knowledge Gateway | `KnowledgeGatewayClient` 作为边界 | pending |
| Runtime 不直接暴露 Vault 文件访问给 Agent | Agent handler 只接收 `RuntimeContext` | pending |
| Runtime 不修改 `llm_wiki.exe` | 本阶段无 llm_wiki 二进制变更 | pending |
| Runtime 不迁移旧笔记 | 本阶段无旧笔记迁移动作 | pending |

## 4. 安全边界验收

| Check | Required Result | Human Decision |
|---|---|---|
| Agent 未激活不能执行 | 必须拒绝，抛出 `agent_not_active` | pending |
| Agent 缺少权限不能执行对应动作 | 必须拒绝，抛出 `*_denied` | pending |
| Agent 读取知识必须走 Gateway | `ContextManager -> KnowledgeGatewayClient -> KnowledgeGateway` | pending |
| Agent 修改知识必须走 Proposal | `request_update()` 只生成 Proposal | pending |
| Human Approval 通过前不得写入知识 | Gateway 只在 `approve_change()` 后写入 | pending |
| Tool 调用必须走 Tool Manager | Agent 只能使用 `context.tools.call()` | pending |
| 未注册工具必须被拒绝 | `tool_denied` | pending |
| 工具参数不得写入 Runtime 日志 | `events.jsonl` 不记录 kwargs | pending |
| 高敏 Access Grant 只能一次性使用 | `approved -> used`，重复使用拒绝 | pending |
| 高敏上下文不得上云 | `level_3` / `level_4` 强制 local model | pending |

## 5. Network / Model 验收

当前冻结配置：

```yaml
network_mode: OFF
local_model: qwen3:8b
cloud_model: deepseek-reasoner
retry:
  max_attempts: 1
```

| Check | Required Result | Human Decision |
|---|---|---|
| 默认网络模式是 `OFF` | `config/network.yaml` | pending |
| 非法网络模式被拒绝 | `RuntimePolicy` 抛出 `ValueError` | pending |
| `OFF` 下复杂任务仍走本地模型 | `ModelRouter` 返回 `provider=local` | pending |
| `ASSIST` / `SYNC` 不自动写入知识 | 只允许查询 / Inbox / 审核流程 | pending |
| `level_3` / `level_4` 强制本地模型 | `reason=sensitive_context_requires_local_model` | pending |

## 6. 审计验收

Runtime 必须记录关键行为，并避免泄露正文。

### 必须记录的事件

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

### 不得写入 Runtime 日志的内容

- Tool 参数。
- Agent exception 原文。
- Tool exception 原文。
- Proposal `old` / `new` 正文。
- Proposal review reason 正文。
- Knowledge node body。
- Prompt 正文。
- Access Request reason 正文。
- Monitor / Update detail 值。

人工确认：

```text
audit coverage accepted: yes / no
```

## 7. 测试验收

收口前需要一轮 fresh verification。

### Runtime focused tests

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest tests/test_runtime_core.py tests/test_runtime_gateway_client.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
```

当前最近证据：

```text
30 passed
```

### Full suite

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest -q
```

当前最近证据：

```text
348 passed, 3 skipped, 78 subtests passed
```

### Diff whitespace

```powershell
git diff --check
```

当前最近证据：

```text
passed
```

人工确认：

```text
verification accepted: yes / no
```

## 8. 明确未验收事项

以下内容不属于 Phase 2 Runtime 验收范围，不能因为 Runtime 收口而视为完成：

- Knowledge Agent 实现。
- Body Agent / Study Agent / Project Agent 实现。
- Feishu Approval 真实联动。
- Obsidian 插件或自动化集成。
- llm_wiki 改造。
- 旧笔记导入或迁移。
- Self Model / Cognitive Proposal 实现。
- 移动端、Tailscale、公网访问。
- 高自治 Agent Sandbox。

## 9. Human Acceptance Decision

人工验收时选择其一。

### Option A: Accept Phase 2 Runtime Closeout

使用条件：

- 上述冻结架构、安全边界、网络模型、审计和测试均接受。
- Human Owner 认可 `Runtime API Contract` 可作为 Phase 3 前置契约。

建议记录：

```text
Phase 2 Runtime Core: closeout accepted
Accepted by:
Accepted at:
Basis:
- Phase_2_Runtime_Closeout_Audit.md
- Runtime_API_Contract.md
- Phase_2_Runtime_Human_Acceptance_Checklist.md
```

接受后允许进入的下一步：

```text
Phase 3 Knowledge Agent implementation planning
```

注意：接受 Phase 2 不等于批准直接实现 Phase 3 Agent。Phase 3 仍需要独立实施计划和明确授权。

### Option B: Request Runtime Fixes Before Acceptance

使用条件：

- 发现权限、审计、网络、Gateway、Proposal 或测试证据不足。

建议记录：

```text
Phase 2 Runtime Core: changes requested
Required fixes:
1.
2.
3.
```

### Option C: Keep Closeout Candidate

使用条件：

- 当前没有发现阻断问题，但暂不做正式验收决定。

建议记录：

```text
Phase 2 Runtime Core: closeout candidate retained
Reason:
Next review date:
```

## 10. Recommended Human Review Path

建议人工审核顺序：

1. 阅读 [Phase 2 Runtime 收口审计报告](Phase_2_Runtime_Closeout_Audit.md)。
2. 阅读 [Runtime API Contract](Runtime_API_Contract.md)。
3. 对照本清单检查安全边界。
4. 若接受，指示 Codex 标记 `closeout accepted`。
5. 若不接受，列出必须修复项。
6. 只有在 Phase 2 accepted 之后，再批准 Phase 3 Knowledge Agent 实施计划。

## 11. Current Recommendation

当前工程状态建议：

```text
Recommend: Option C -> Option A after Human Owner review
```

原因：

- Runtime 已有收口审计报告。
- Runtime API Contract 已生成。
- 当前测试证据支持进入人工验收。
- 但 Human Approval 是系统治理边界，不能由 Agent 自行把 closeout candidate 改成 accepted。
