# Runtime API Contract

Version: v0.1
Date: 2026-08-05
Scope: Personal Knowledge OS Phase 2 Runtime Core
Status: Phase 3 pre-entry contract

## 1. Contract Purpose

本文档定义 Phase 3 Agent 接入 `runtime_core` 时必须遵守的工程契约。

它不是 Agent 实现计划，也不授权进入 Phase 3。它的作用是冻结 Phase 2 Runtime 对外接口，让后续 Knowledge Agent、Body Agent、Study Agent、Project Agent 只能通过受控入口接入系统。

## 2. Non-Negotiable Architecture Boundaries

所有 Agent 必须遵守以下边界：

1. Agent 必须注册到 `RuntimeKernel`，不得临时创建后直接运行。
2. Agent 必须由 `RuntimeKernel.activate_agent()` 激活后才能执行。
3. Agent Handler 接收 `RuntimeContext`，不得接收 Vault 文件路径作为工作入口。
4. Agent 读取知识只能通过 `RuntimeContext.knowledge` / `experience` / `principles`。
5. Agent 修改知识只能调用 Runtime Proposal 接口，不能直接写 Markdown。
6. Agent 调用工具只能通过 `RuntimeContext.tools.call()`。
7. Agent 访问高敏上下文必须先创建并获得 Access Request。
8. Runtime state 必须放在 Knowledge Vault 外部。
9. 默认 `network_mode` 必须是 `OFF`。
10. `level_3` / `level_4` 上下文必须强制使用本地模型。

禁止：

```text
Agent -> open Markdown -> direct write
Agent -> external API directly
Agent -> llm_wiki.exe modification
Agent -> old notes migration
Agent -> Vault bypass
```

允许：

```text
Agent -> RuntimeKernel -> PermissionManager -> KnowledgeGatewayClient -> KnowledgeGateway
Agent -> RuntimeKernel -> ToolManager -> registered tool
Agent -> RuntimeKernel -> ApprovalEngine -> Proposal -> Human Review
```

## 3. Import Surface

Phase 3 Agent 只应依赖 `runtime_core` 当前公开导出：

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

不要从 `runtime_core.kernel` 等内部模块导入私有辅助函数。

## 4. Configuration Contract

Runtime 配置来源：

```text
config/
├── network.yaml
├── model.yaml
└── runtime.yaml
```

`network.yaml`：

```yaml
network_mode: OFF
```

合法值：

| Mode | Meaning | Write Permission |
|---|---|---|
| `OFF` | 完全本地，本地知识、本地模型、本地 Runtime | 禁止自动写入 |
| `ASSIST` | 允许辅助查询和复杂分析 | 禁止自动写入 / 自动同步 |
| `SYNC` | 外部内容只能进入 Inbox 等待审核 | 禁止绕过审核写入正式知识 |

`model.yaml`：

```yaml
local_model: qwen3:8b
cloud_model: deepseek-reasoner
```

`runtime.yaml`：

```yaml
retry:
  max_attempts: 1
```

约束：

- `network_mode` 非 `OFF` / `ASSIST` / `SYNC` 必须拒绝。
- `retry.max_attempts` 必须大于等于 `1`。
- 缺失 `runtime.yaml` 时默认 `max_attempts = 1`。
- `OFF` 下复杂任务仍应使用本地模型。

## 5. Agent Definition Contract

Agent 必须用 `AgentDefinition` 显式定义身份、领域、自治等级、风险等级和权限。

```python
from runtime_core import AgentDefinition

def handler(context):
    return {
        "agent_id": context.agent_id,
        "model_provider": context.model.provider,
        "knowledge_ids": [node.id for node in context.knowledge],
    }

definition = AgentDefinition(
    agent_id="knowledge_agent",
    name="Knowledge Agent",
    domain="knowledge",
    autonomy_level=2,
    risk_level="medium",
    permissions=("execute", "read_knowledge", "propose_change"),
    handler=handler,
    description="Reads governed knowledge and proposes reviewed changes.",
    model_policy="local_first",
)
```

字段约束：

| Field | Type | Constraint |
|---|---|---|
| `agent_id` | `str` | 必填，非空，系统内唯一 |
| `name` | `str` | 必填，非空 |
| `domain` | `str` | 必填，非空 |
| `autonomy_level` | `int` | `0..4` |
| `risk_level` | `str` | `low` / `medium` / `high` |
| `permissions` | `tuple[str, ...]` | 最小权限集合 |
| `handler` | `Callable[[RuntimeContext], Any]` | 必须可调用 |
| `description` | `str` | 可选 |
| `model_policy` | `str` | 当前默认 `local_first` |

## 6. Runtime Kernel Contract

推荐从冻结配置创建 Runtime：

```python
from runtime_core import KnowledgeGatewayClient, RuntimeKernel, load_runtime_policy

policy = load_runtime_policy("config")

kernel = RuntimeKernel.from_policy(
    gateway_client=KnowledgeGatewayClient(gateway),
    state_path="runtime_state",
    policy=policy,
)
```

构造约束：

- `gateway` 和 `gateway_client` 二选一。
- 不允许同时传入 `gateway` 与 `gateway_client`。
- 必须传入 `state_path`。
- `state_path` 必须位于 Knowledge Vault 外部。
- `default_network_mode` 必须是 `OFF` / `ASSIST` / `SYNC`。

Runtime state 输出：

```text
runtime_state/
├── access_requests/
├── events.jsonl
└── memory.jsonl
```

## 7. Agent Lifecycle Contract

Agent 生命周期：

```text
register -> activate -> execute -> monitor -> update -> deactivate
```

标准调用：

```python
kernel.register_agent(definition)
kernel.activate_agent("knowledge_agent")

result = kernel.execute(
    "knowledge_agent",
    credential="<agent-credential>",
    task="schema",
    complexity="standard",
)
```

执行约束：

- 未注册 Agent 必须失败。
- 未激活 Agent 执行必须抛出 `AgentLifecycleError("agent_not_active")`。
- 没有 `execute` 权限必须抛出 `PermissionDenied("execute_denied")`。
- Retry 不得绕过权限检查、生命周期检查或 Gateway 边界。

## 8. Runtime Context Contract

Agent Handler 只能使用 `RuntimeContext` 提供的受控字段：

```python
RuntimeContext(
    agent_id: str,
    task: str,
    model: ModelRoute,
    knowledge: list[GatewayNode],
    experience: list[GatewayNode],
    principles: list[GatewayNode],
    memory: MemoryManager,
    tools: BoundToolManager,
    approvals: ApprovalEngine,
)
```

Agent 可以：

- 读取 `knowledge` / `experience` / `principles` 中已授权节点。
- 使用 `memory.recent()` / `memory.size()` 查看自身运行记忆。
- 使用 `tools.call()` 调用已注册工具。
- 使用 `approvals` 相关能力提出 Proposal。

Agent 不可以：

- 通过 `path` 字段自行打开 Markdown。
- 把 `GatewayNode.body` 直接发送到云端模型，尤其是 `level_3` / `level_4`。
- 将工具参数或知识正文写入审计日志。

## 9. Permission Contract

当前 Runtime 权限字符串采用最小权限模型。

常用权限：

| Permission | Meaning |
|---|---|
| `execute` | 允许 Runtime 执行 Agent handler |
| `read_knowledge` | 允许经 Gateway 构建上下文 |
| `propose_change` | 允许创建知识修改 Proposal |
| `request_access` | 允许请求高敏上下文授权 |
| `use_tools` | 允许调用要求该权限的工具 |

权限缺失时，Runtime 必须拒绝并抛出 `PermissionDenied("<permission>_denied")`。

## 10. Knowledge Access Contract

普通上下文：

```python
context = kernel.get_context(
    "knowledge_agent",
    credential="<agent-credential>",
    task="schema",
)
```

执行时自动构建上下文：

```python
result = kernel.execute(
    "knowledge_agent",
    credential="<agent-credential>",
    task="schema",
)
```

实际路径：

```text
RuntimeKernel
-> ContextManager
-> KnowledgeGatewayClient
-> KnowledgeGateway
-> Markdown Vault
```

约束：

- Agent 必须拥有 `read_knowledge`。
- Gateway 负责 folder / metadata / agent policy 过滤。
- Runtime 不暴露 Vault 根目录给 Agent。
- `KnowledgeGatewayClient` 是 Runtime 与 Gateway 的稳定边界。

## 11. Sensitive Access Request Contract

高敏上下文必须走 Access Request。

```python
request = kernel.request_access(
    "knowledge_agent",
    resource="03_Principles/study/core.md",
    reason="Need owner-approved context for one reviewed analysis.",
    sensitivity="level_3",
)

approved = kernel.approve_access_request(
    request.request_id,
    reviewer="owner",
    reason="Approved for this single task.",
)

context = kernel.get_context_with_access(
    "knowledge_agent",
    credential="<agent-credential>",
    task="core",
    access_request_id=approved.request_id,
)
```

Access Request 状态：

```text
pending -> approved -> used
pending -> rejected
```

约束：

- 创建请求必须拥有 `request_access`。
- `sensitivity` 必须是 `level_0..level_4`。
- `pending` / `rejected` 不可使用。
- `approved` 只能使用一次。
- 请求只能由原 Agent 使用。
- 访问仍必须经过 Knowledge Gateway。

## 12. Proposal Contract

知识修改只能通过 Proposal。

```python
proposal = kernel.request_update(
    "knowledge_agent",
    credential="<agent-credential>",
    target_id="KN-001",
    old="old text",
    new="new text",
    reason="Explain why this change is proposed.",
    confidence=0.82,
    risk="medium",
)
```

人工审核：

```python
approved = kernel.approve_change(
    proposal.proposal_id,
    reviewer="owner",
    reviewer_credential="<reviewer-credential>",
)
```

也可以：

```python
kernel.reject_change(
    proposal.proposal_id,
    reviewer="owner",
    reviewer_credential="<reviewer-credential>",
    reason="Keep current wording.",
)

kernel.expire_change(
    proposal.proposal_id,
    reviewer="owner",
    reviewer_credential="<reviewer-credential>",
    reason="Review window closed.",
)
```

约束：

- 创建 Proposal 必须拥有 `propose_change`。
- `confidence` 必须在 `0.0..1.0`。
- `risk` 必须是 `low` / `medium` / `high`。
- `old` 必须在目标 Markdown 中恰好出现一次。
- `old` / `new` / `reason` 不得写入 Runtime `events.jsonl`。
- 真正写入 Markdown 只能在 Human Approval 通过后由 Gateway 执行。

## 13. Tool Contract

工具必须先由 Runtime 注册：

```python
kernel.tools.register(
    "summarize_local",
    lambda text: text[:200],
    required_permission="use_tools",
)
```

Agent 内只能这样调用：

```python
def handler(context):
    return context.tools.call("summarize_local", text="local-only content")
```

约束：

- 未注册工具必须拒绝并记录 `tool_denied`。
- 缺少工具权限必须拒绝并记录 `tool_denied`。
- 工具执行失败必须记录 `tool_failed`。
- `tool_called` / `tool_denied` / `tool_failed` 不得记录工具参数。
- Agent 不得直接调用外部 API；外部能力必须封装为 Runtime 注册工具。

## 14. Model Routing Contract

模型路由由 Runtime 选择：

```python
route = context.model
```

`ModelRoute`：

```python
ModelRoute(
    provider: str,
    model_name: str,
    reason: str,
)
```

路由规则：

| Condition | Provider | Reason |
|---|---|---|
| 默认 / `OFF` | `local` | `local_first` |
| `ASSIST` 或 `SYNC` 且 `complexity` 为 `complex` / `deep` / `high` | `cloud` | `complex_task_with_network_enabled` |
| 上下文最高敏感度为 `level_3` / `level_4` | `local` | `sensitive_context_requires_local_model` |

高敏规则优先级最高。

## 15. Audit Event Contract

Runtime 必须记录关键行为。

当前事件：

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

脱敏规则：

- Agent 失败只记录 `error_type`。
- Tool 失败只记录 `error_type`。
- Tool 参数不入日志。
- Proposal 的 `old` / `new` / review reason 正文不入日志。
- Monitor / Update 只记录 detail 字段名，不记录字段值。
- Access Request denied 不记录 request reason。
- Model route 不记录知识正文、Prompt 或上下文正文。

## 16. Runtime Memory Contract

Runtime 当前记忆是执行记忆，不是长期知识事实源。

```python
context.memory.size("knowledge_agent")
context.memory.recent("knowledge_agent", limit=5)
```

约束：

- `memory.jsonl` 存放在 Runtime state。
- Runtime memory 不得替代 Knowledge Vault。
- 需要长期沉淀的内容必须进入 Proposal / Human Approval / Vault 流程。

## 17. Phase 3 Agent Entry Checklist

任何 Phase 3 Agent 开始实现前，必须满足：

- [ ] Agent 有唯一 `agent_id`。
- [ ] Agent 有明确 `domain`。
- [ ] Agent `autonomy_level` 不超过当前批准范围。
- [ ] Agent `risk_level` 已声明。
- [ ] Agent 权限为最小集合。
- [ ] Agent Handler 只接收 `RuntimeContext`。
- [ ] Agent 不直接打开 Vault 文件。
- [ ] Agent 不直接调用外部 API。
- [ ] Agent 写入知识只走 Proposal。
- [ ] 高敏上下文只走 Access Request。
- [ ] 网络默认 `OFF`。
- [ ] `level_3` / `level_4` 不上云。
- [ ] 新增行为有测试。
- [ ] 新增关键事件有审计。

## 18. Verification Commands

Runtime 契约相关最小验证：

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest tests/test_runtime_core.py tests/test_runtime_gateway_client.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
```

完整验证：

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest -q
```

格式检查：

```powershell
git diff --check
```

## 19. Contract Status

当前判断：

```text
Runtime API Contract: ready for human review
```

本契约可以作为 Phase 3 Agent Implementation 的前置审查材料。

它不代表 Phase 3 已经开始，也不代表任何 Agent 已经被授权实现。
