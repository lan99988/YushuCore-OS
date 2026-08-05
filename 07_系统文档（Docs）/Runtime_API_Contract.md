# Runtime API Contract

Version: v1.0
Date: 2026-08-05
Scope: Personal Knowledge OS Phase 2 Runtime Core
Status: Frozen / Phase 3 entry contract

## 1. Contract Purpose

本文档定义 Phase 3 Agent 接入 `runtime_core` 时必须遵守的公共契约。

Runtime API 已随 Phase 2 Runtime 验收正式冻结。Phase 3 可以在 Agent 层扩展能力，但不得随意修改 Runtime Core 的公共接口、目录结构或安全边界。

## 2. Frozen Import Surface

Phase 3 Agent 只能依赖 `runtime_core/__init__.py` 当前公开导出：

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

禁止 Agent 直接依赖 `runtime_core.kernel`、`runtime_core.context`、`runtime_core.tools` 等内部模块中的私有辅助函数。

## 3. Public API

### RuntimeKernel

```python
RuntimeKernel(
    *,
    gateway=None,
    gateway_client=None,
    state_path,
    local_model,
    cloud_model,
    model_router=None,
    default_network_mode="OFF",
    retry_max_attempts=1,
)

RuntimeKernel.from_policy(
    *,
    gateway=None,
    gateway_client=None,
    state_path,
    policy,
)

register_agent(definition)
load_agents_from_file(path, *, handlers)
activate_agent(agent_id)
deactivate_agent(agent_id)
execute(agent_id, *, credential, task, complexity="standard", network_mode=None)
monitor_agent(agent_id, *, check)
update_agent(agent_id, *, changes)
request_update(agent_id, *, credential, target_id, old, new, reason, confidence, risk)
approve_change(proposal_id, *, reviewer, reviewer_credential)
reject_change(proposal_id, *, reviewer, reviewer_credential, reason)
expire_change(proposal_id, *, reviewer, reviewer_credential, reason)
request_access(agent_id, *, resource, reason, sensitivity)
approve_access_request(request_id, *, reviewer, reason)
reject_access_request(request_id, *, reviewer, reason)
get_context(agent_id, *, credential, task)
get_context_with_access(agent_id, *, credential, task, access_request_id)
```

### AgentDefinition

```python
AgentDefinition(
    agent_id: str,
    name: str,
    domain: str,
    autonomy_level: int,
    risk_level: str,
    permissions: tuple[str, ...],
    handler,
    description: str = "",
    model_policy: str = "local_first",
)
```

### RuntimeContext

```python
RuntimeContext(
    agent_id: str,
    task: str,
    model: ModelRoute,
    knowledge: list,
    experience: list,
    principles: list,
    memory,
    tools,
    approvals,
)
```

### RuntimeResult

```python
RuntimeResult(
    agent_id: str,
    task: str,
    output,
    model: ModelRoute,
)
```

### ModelRoute / ModelRouter

```python
ModelRoute(provider: str, model_name: str, reason: str)

ModelRouter(local_model: str, cloud_model: str)
ModelRouter.select(
    *,
    complexity: str,
    network_mode: str,
    max_context_sensitivity: str = "level_0",
)
```

### RuntimePolicy

```python
RuntimePolicy(
    network_mode: str,
    local_model: str,
    cloud_model: str,
    retry=RetryPolicy(max_attempts=1),
)

RuntimePolicy.model_router()
RuntimePolicy.with_retry(
    *,
    network_mode,
    local_model,
    cloud_model,
    retry_max_attempts,
)

load_runtime_policy(config_dir)
```

### KnowledgeGatewayClient

```python
KnowledgeGatewayClient(gateway)

get_context(*args, **kwargs)
get_context_with_access_grant(*args, **kwargs)
request_update(*args, **kwargs)
approve_change(*args, **kwargs)
reject_change(*args, **kwargs)
expire_change(*args, **kwargs)
```

### AccessRequest

```python
AccessRequest(
    request_id,
    agent_id,
    resource,
    reason,
    sensitivity,
    status,
    created,
    reviewer=None,
    review_reason=None,
    review_time=None,
)

AccessRequest.to_dict()
AccessRequest.from_dict(value)
```

### Exceptions

```python
PermissionDenied
AgentLifecycleError
AccessRequestDenied
```

## 4. Non-Negotiable Architecture Boundaries

Agent 必须遵守：

1. Agent 必须注册到 `RuntimeKernel`。
2. Agent 必须经 `RuntimeKernel.activate_agent()` 激活后才能执行。
3. Agent Handler 只接收 `RuntimeContext`。
4. Agent 不得以 Vault 文件路径作为工作入口。
5. Agent 读取知识只能使用 `RuntimeContext.knowledge`、`RuntimeContext.experience`、`RuntimeContext.principles`。
6. Agent 修改知识只能走 `RuntimeKernel.request_update()` 与 Approval 流程。
7. Agent 调用工具只能走 `RuntimeContext.tools.call()`。
8. Agent 访问高敏上下文必须先创建并获得 Access Request。
9. Runtime state 必须位于 Knowledge Vault 外部。
10. 默认 `network_mode` 必须为 `OFF`。
11. `level_3` / `level_4` 上下文必须强制使用本地模型。

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

## 5. Configuration Contract

配置来源：

```text
config/
├── network.yaml
├── model.yaml
└── runtime.yaml
```

当前基线：

```yaml
network_mode: OFF
local_model: qwen3:8b
cloud_model: deepseek-reasoner
retry:
  max_attempts: 1
```

网络模式：

| Mode | Meaning | Write Permission |
|---|---|---|
| `OFF` | 完全本地 | 禁止自动写入 |
| `ASSIST` | 允许辅助查询和复杂分析 | 禁止自动写入 / 自动同步 |
| `SYNC` | 外部内容只能进入 Inbox 等待审核 | 禁止绕过审核写入正式知识 |

## 6. Permission Contract

常用权限：

| Permission | Meaning |
|---|---|
| `execute` | 允许 Runtime 执行 Agent handler |
| `read_knowledge` | 允许通过 Gateway 构建上下文 |
| `propose_change` | 允许创建知识修改 Proposal |
| `request_access` | 允许请求高敏上下文临时授权 |
| `use_tools` | 允许调用需要该权限的工具 |

权限缺失时，Runtime 必须拒绝并抛出 `PermissionDenied("<permission>_denied")`。

## 7. Runtime API Change Control

Runtime API 已冻结。Phase 3 期间如果确需修改公共接口，必须执行：

```text
Proposal -> Review -> Approval -> Migration
```

变更 Proposal 至少包含：

- 要修改的 API
- 修改原因
- 是否破坏兼容
- 影响的 Agent
- 替代方案
- 迁移步骤
- 回滚方案
- 测试计划

未经 Human Owner 单独批准，不得合并 Runtime API 破坏性改动。

## 8. Phase 3 Agent Entry Checklist

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

## 9. Verification Commands

Runtime 相关最小验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_core.py tests/test_runtime_gateway_client.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
```

完整验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

格式检查：

```powershell
git diff --check
```

## 10. Contract Status

```text
Runtime API Contract: frozen
Frozen at: phase2-runtime-accepted-v1.0
Owner: Human Owner
```
