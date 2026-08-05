# Phase 2 Runtime Final Report

Version: v1.0
Date: 2026-08-05
Status: Accepted
Git Tag: `phase2-runtime-accepted-v1.0`

## 1. Final Summary

Phase 2 Runtime Core 已经完成并通过 Human Owner 验收。

Runtime 的定位是 Personal AI OS 的执行内核。它不保存长期知识事实，不替代 Knowledge Vault，不直接修改 Markdown，而是负责统一管理：

- Agent 生命周期
- 权限检查
- 上下文构建
- 运行记忆
- 模型路由
- 工具调用
- Proposal / Approval
- 临时访问授权
- 事件与审计日志

Phase 3 Agent Implementation 必须依赖本报告和 [Runtime API Contract](Runtime_API_Contract.md) 中冻结的 Runtime 能力。

## 2. 最终目录结构

当前与 Runtime / Knowledge OS 相关的工程目录：

```text
D:\个人混合管理系统
├── config
│   ├── network.yaml
│   ├── model.yaml
│   └── runtime.yaml
├── knowledge_system
├── runtime
├── runtime_core
│   ├── __init__.py
│   ├── access.py
│   ├── approval.py
│   ├── config.py
│   ├── context.py
│   ├── events.py
│   ├── gateway_client.py
│   ├── kernel.py
│   ├── logger.py
│   ├── memory.py
│   ├── models.py
│   ├── permissions.py
│   ├── policy.py
│   ├── registry.py
│   ├── router.py
│   ├── scheduler.py
│   └── tools.py
├── tests
│   ├── test_runtime_core.py
│   ├── test_runtime_gateway_client.py
│   ├── test_runtime_policy.py
│   └── test_runtime_scheduler.py
└── 07_系统文档（Docs）
    ├── Phase_2_Runtime_Core_Report.md
    ├── Phase_2_Runtime_Closeout_Audit.md
    ├── Runtime_API_Contract.md
    ├── Phase_2_Runtime_Human_Acceptance_Checklist.md
    ├── Phase_2_Runtime_Acceptance_Decision_Record.md
    ├── Phase_2_Runtime_Final_Report.md
    ├── Phase_3_Technical_Design.md
    └── ADR
```

Runtime 运行态目录由 `state_path` 指定，必须位于 Knowledge Vault 外部：

```text
runtime_state/
├── access_requests/
├── events.jsonl
└── memory.jsonl
```

## 3. Runtime 模块结构

| 模块 | 职责 |
|---|---|
| `runtime_core/__init__.py` | 收敛 Phase 3 可依赖的公开导出 |
| `runtime_core/kernel.py` | RuntimeKernel，总编排入口 |
| `runtime_core/models.py` | AgentDefinition、RuntimeContext、RuntimeResult、ModelRoute 等数据契约 |
| `runtime_core/registry.py` | Agent 注册表 |
| `runtime_core/scheduler.py` | Agent 激活、停用、监控、更新与生命周期状态 |
| `runtime_core/permissions.py` | 最小权限检查 |
| `runtime_core/context.py` | 经 Gateway Client 构建知识上下文 |
| `runtime_core/memory.py` | JSONL 运行记忆 |
| `runtime_core/router.py` | Local First / 敏感度感知模型路由 |
| `runtime_core/tools.py` | 工具注册、绑定、调用、权限校验和审计 |
| `runtime_core/approval.py` | 知识修改 Proposal 审批门面 |
| `runtime_core/access.py` | 高敏上下文临时访问授权 |
| `runtime_core/events.py` | Event Bus 内存事件流 |
| `runtime_core/logger.py` | Runtime JSONL 审计日志 |
| `runtime_core/policy.py` | Runtime 策略加载 |
| `runtime_core/config.py` | AgentDefinition YAML 加载 |
| `runtime_core/gateway_client.py` | Runtime 与 Knowledge Gateway 的边界适配 |

## 4. 所有公开 API

Phase 3 只应从 `runtime_core` 顶层导入：

```python
from runtime_core import (
    AccessRequest,
    AccessRequestDenied,
    AgentDefinition,
    AgentLifecycleError,
    KnowledgeGatewayClient,
    ModelRoute,
    ModelRouter,
    PermissionDenied,
    RuntimeContext,
    RuntimeKernel,
    RuntimePolicy,
    RuntimeResult,
    load_runtime_policy,
)
```

### RuntimeKernel

```python
RuntimeKernel.from_policy(...)
RuntimeKernel.register_agent(definition)
RuntimeKernel.load_agents_from_file(path, *, handlers)
RuntimeKernel.activate_agent(agent_id)
RuntimeKernel.deactivate_agent(agent_id)
RuntimeKernel.execute(agent_id, *, credential, task, complexity="standard", network_mode=None)
RuntimeKernel.monitor_agent(agent_id, *, check)
RuntimeKernel.update_agent(agent_id, *, changes)
RuntimeKernel.request_update(agent_id, *, credential, target_id, old, new, reason, confidence, risk)
RuntimeKernel.approve_change(proposal_id, *, reviewer, reviewer_credential)
RuntimeKernel.reject_change(proposal_id, *, reviewer, reviewer_credential, reason)
RuntimeKernel.expire_change(proposal_id, *, reviewer, reviewer_credential, reason)
RuntimeKernel.request_access(agent_id, *, resource, reason, sensitivity)
RuntimeKernel.approve_access_request(request_id, *, reviewer, reason)
RuntimeKernel.reject_access_request(request_id, *, reviewer, reason)
RuntimeKernel.get_context(agent_id, *, credential, task)
RuntimeKernel.get_context_with_access(agent_id, *, credential, task, access_request_id)
```

### Data Contracts

```python
AgentDefinition(...)
RuntimeContext(...)
RuntimeResult(...)
ModelRoute(...)
AccessRequest(...)
RuntimePolicy(...)
```

### Supporting APIs

```python
load_runtime_policy(config_dir)
ModelRouter.select(...)
KnowledgeGatewayClient(...)
```

### Exceptions

```python
PermissionDenied
AgentLifecycleError
AccessRequestDenied
```

内部模块中的 `AgentRegistry`、`AgentScheduler`、`PermissionManager`、`ContextManager`、`MemoryManager`、`ToolManager`、`ApprovalEngine`、`EventBus`、`RuntimeLogger` 等属于 Runtime Core 内部结构。Phase 3 Agent 不应直接依赖这些内部类，除非后续通过正式 API Proposal 将其纳入公共契约。

## 5. Agent 生命周期

标准生命周期：

```text
define -> register -> activate -> execute -> monitor/update -> deactivate
```

执行约束：

1. 未注册 Agent 不可执行。
2. 未激活 Agent 执行时必须失败。
3. Agent 必须拥有 `execute` 权限。
4. Runtime 在执行前构建受控上下文。
5. Runtime 根据上下文敏感度选择模型。
6. Runtime 将 `RuntimeContext` 传入 Agent handler。
7. 成功执行后写入 Memory。
8. 执行过程写入 Event Bus / Audit Log。

关键事件：

```text
agent_activated
agent_deactivated
agent_started
agent_retry
agent_failed
agent_completed
agent_monitored
agent_updated
```

## 6. 权限模型

Runtime 采用最小权限字符串模型。权限不是身份附属的无限授权，而是 AgentDefinition 中显式声明的最小能力集合。

常用权限：

| Permission | Meaning |
|---|---|
| `execute` | 允许 Runtime 执行 Agent handler |
| `read_knowledge` | 允许通过 Gateway 构建上下文 |
| `propose_change` | 允许创建知识修改 Proposal |
| `request_access` | 允许请求高敏上下文临时授权 |
| `use_tools` | 允许调用需要该权限的工具 |

权限流程：

```text
Agent action
-> RuntimeKernel
-> PermissionManager.require()
-> allow / PermissionDenied
-> audit event
```

Phase 3 不能引入“万能 Agent”。每个 Agent 必须声明自己的 domain、risk_level、autonomy_level 和最小权限集。

## 7. Context 流程

普通上下文：

```text
RuntimeKernel.get_context() / execute()
-> ContextManager.build()
-> PermissionManager.require(read_knowledge)
-> KnowledgeGatewayClient.get_context()
-> Knowledge Gateway
-> authorized GatewayNode lists
-> RuntimeContext
-> Agent handler
```

高敏上下文：

```text
RuntimeKernel.request_access()
-> Human Approval
-> RuntimeKernel.get_context_with_access()
-> verify request owner / status / one-time use
-> KnowledgeGatewayClient.get_context_with_access_grant()
-> mark access request used
-> RuntimeContext
```

约束：

- Runtime 不暴露 Vault 根路径给 Agent。
- Agent 不得直接打开 Markdown 文件。
- `level_3` / `level_4` 上下文强制本地模型。

## 8. Memory 流程

Runtime Memory 是执行记忆，不是长期知识事实源。

```text
Agent execution succeeds
-> MemoryManager.record(agent_id, task, output)
-> runtime_state/memory.jsonl
-> context.memory.recent(agent_id)
-> context.memory.size(agent_id)
```

约束：

- Memory 不替代 Knowledge Vault。
- 需要长期沉淀的内容必须进入 Proposal / Human Approval / Vault 流程。
- Memory 写入在 Runtime state 中，不写入 Knowledge Vault。

## 9. Model Router 流程

路由策略：

| Condition | Provider | Reason |
|---|---|---|
| 默认或 `OFF` | `local` | `local_first` |
| `ASSIST` / `SYNC` 且任务复杂度为 `complex` / `deep` / `high` | `cloud` | `complex_task_with_network_enabled` |
| 上下文最高敏感度为 `level_3` / `level_4` | `local` | `sensitive_context_requires_local_model` |

流程：

```text
Context built
-> calculate max_context_sensitivity
-> ModelRouter.select()
-> model_route_selected event
-> RuntimeContext.model
-> Agent handler
```

高敏规则优先级最高。即使网络模式允许云端分析，高敏上下文仍必须走本地模型。

## 10. Event Bus 流程

Runtime 使用 Event Bus 连接内存事件历史与 JSONL 审计日志。

```text
Runtime action
-> EventBus.publish(event)
-> in-memory history
-> RuntimeLogger.write(event)
-> runtime_state/events.jsonl
```

审计脱敏规则：

- Agent 失败只记录 `error_type`。
- Tool 失败只记录 `error_type`。
- Tool 参数不入日志。
- Proposal 的 `old` / `new` / `reason` 正文不入日志。
- Monitor / Update 只记录字段名，不记录字段值。
- Access Request denied 不记录 request reason。
- Model route 不记录知识正文、prompt 或上下文正文。

## 11. 已知限制（Known Limitations）

1. Runtime 目前是本地进程内内核，不是多进程服务。
2. Agent Registry 尚未提供远程注册协议。
3. 权限模型当前以字符串权限为主，尚未实现完整策略 DSL。
4. Runtime Memory 是 JSONL 执行记忆，不是语义长期记忆。
5. Event Bus 是进程内事件总线，不是跨进程消息系统。
6. Tool Manager 已有权限与审计边界，但外部工具适配器仍需 Phase 3/4 扩展。
7. Access Request 是本地状态存储，尚未接入正式 UI 审核入口。
8. Model Router 已实现关键安全路由，但未做成本、延迟、模型健康度调度。
9. Runtime 不负责旧笔记迁移。
10. Runtime 不修改 `llm_wiki.exe`。

## 12. 后续扩展点（Extension Points）

Phase 3/4 可以在不破坏 Runtime API 的前提下扩展：

- Agent SDK：封装 AgentDefinition 与 handler 模式。
- Agent manifests：用 YAML 注册 Agent。
- Skill 接口：把技能作为 Runtime 工具或 Agent 能力声明。
- Tool adapters：Feishu、Obsidian、llm_wiki、外部 API 的受控工具封装。
- Review UI：Proposal 与 Access Request 的人工审核入口。
- Policy DSL：更精细的权限策略。
- Event consumers：将 Runtime 事件接入 Dashboard。
- Memory compaction：把运行记忆转为 Proposal，而不是直接写 Vault。
- Model health routing：在不破坏高敏本地规则的前提下增加可用性判断。

## 13. Phase 3 将依赖哪些 Runtime 能力

Phase 3 Agent Implementation 必须依赖以下 Runtime 能力：

| Phase 3 能力 | 依赖 Runtime 能力 |
|---|---|
| Agent 注册 | `AgentDefinition`、`RuntimeKernel.register_agent()` |
| Agent 启动 | `RuntimeKernel.activate_agent()` |
| Agent 执行 | `RuntimeKernel.execute()`、`RuntimeContext` |
| 知识读取 | `RuntimeContext.knowledge`、`KnowledgeGatewayClient.get_context()` |
| 知识修改提议 | `RuntimeKernel.request_update()`、Approval Engine |
| 高敏访问 | `RuntimeKernel.request_access()`、`get_context_with_access()` |
| 工具调用 | `RuntimeContext.tools.call()` |
| 运行记忆 | `RuntimeContext.memory.recent()`、`memory.size()` |
| 模型选择 | `RuntimeContext.model`、`ModelRouter` |
| 审计 | `EventBus`、`RuntimeLogger` |

## 14. 验证证据

本报告生成前的只读核对确认：

```text
Runtime focused tests: 30 passed
```

最终提交前仍需重新运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_core.py tests/test_runtime_gateway_client.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```
