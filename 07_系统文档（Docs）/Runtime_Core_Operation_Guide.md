# Runtime Core Operation Guide

Date: 2026-08-04

Scope: Personal Knowledge OS Phase 2 Runtime Core.

This guide documents how to configure, run, and verify the current `runtime_core` package. It does not connect BodyOS, StudyOS, Feishu, Obsidian, llm_wiki, or any external network service.

## Purpose

`runtime_core` is the controlled execution layer for future Agents.

It provides:

- Agent registration and lifecycle control.
- Permission checks before runtime actions.
- Knowledge context through Knowledge Gateway only.
- Human-approved Access Requests for sensitive context.
- Tool calls through Tool Manager with audit events for successful, denied, and unknown calls, without logging tool arguments.
- Local-first model routing.
- Retry, audit events, and execution memory.

It does not provide:

- Direct Vault file access for Agents.
- Automatic knowledge modification.
- Direct Feishu task execution.
- Network access by default.

## Configuration Reference

Runtime configuration lives in `config/`.

```text
config/
+-- model.yaml
+-- network.yaml
+-- runtime.yaml
```

`config/network.yaml`

```yaml
network_mode: OFF
```

Allowed values:

- `OFF`: local model, local Vault, local Runtime only.
- `ASSIST`: future mode for network-assisted queries without automatic writes.
- `SYNC`: future mode for network content entering Inbox and waiting for review.

`config/model.yaml`

```yaml
local_model: qwen3:8b
cloud_model: deepseek-reasoner
```

`config/runtime.yaml`

```yaml
retry:
  max_attempts: 1
```

`max_attempts` must be at least `1`. A value of `1` means no retry after the first failed execution.

## Public Runtime Surface

Import surface:

```python
from runtime_core import (
    AccessRequest,
    AccessRequestDenied,
    AgentDefinition,
    AgentLifecycleError,
    KnowledgeGatewayClient,
    ModelRouter,
    PermissionDenied,
    RuntimeKernel,
    RuntimePolicy,
    load_runtime_policy,
)
```

Primary objects:

- `RuntimePolicy`: network mode, local/cloud model names, retry policy.
- `RuntimeKernel`: Agent registration, execution, context, access requests, approvals.
- `KnowledgeGatewayClient`: Runtime-facing facade that forwards context and proposal calls to Knowledge Gateway.
- `AgentDefinition`: Agent identity, domain, autonomy level, risk level, permissions, handler.
- `AccessRequest`: pending/approved/rejected request for sensitive context.

## How to Load Runtime Policy

```python
from runtime_core import load_runtime_policy

policy = load_runtime_policy("config")

assert policy.network_mode == "OFF"
assert policy.local_model == "qwen3:8b"
assert policy.retry.max_attempts >= 1
```

Expected behavior:

- `OFF` stays local-first, including deep or complex tasks.
- `level_3` and `level_4` context stays local even when `ASSIST` or `SYNC` would otherwise allow cloud routing.
- Invalid network modes raise `ValueError`.
- Missing `runtime.yaml` defaults to one attempt.

## How to Create a Runtime Kernel

The Runtime can be created with either a `KnowledgeGateway` or a `KnowledgeGatewayClient`. The Gateway remains the only knowledge access boundary.

```python
from runtime_core import KnowledgeGatewayClient, RuntimeKernel, load_runtime_policy

policy = load_runtime_policy("config")

kernel = RuntimeKernel.from_policy(
    gateway_client=KnowledgeGatewayClient(gateway),
    state_path="runtime_state",
    policy=policy,
)
```

Runtime state output:

```text
runtime_state/
+-- access_requests/
+-- events.jsonl
+-- memory.jsonl
```

Keep Runtime state outside the Knowledge Vault.

## How to Register and Run an Agent

```python
from runtime_core import AgentDefinition

def handler(context):
    return {
        "model": context.model.provider,
        "knowledge_ids": [node.id for node in context.knowledge],
    }

kernel.register_agent(
    AgentDefinition(
        agent_id="body_agent",
        name="Body Runtime Agent",
        domain="body",
        autonomy_level=2,
        risk_level="medium",
        permissions=("execute", "read_knowledge"),
        handler=handler,
    )
)

kernel.activate_agent("body_agent")

result = kernel.execute(
    "body_agent",
    credential="<body-agent-credential>",
    task="sleep",
)
```

Expected lifecycle:

```text
Register -> Activate -> Execute -> Monitor -> Update -> Deactivate
```

Execution before activation raises `AgentLifecycleError("agent_not_active")`.

## How to Monitor and Update an Agent

```python
monitor = kernel.monitor_agent(
    "body_agent",
    check=lambda agent: {"healthy": True},
)

update = kernel.update_agent(
    "body_agent",
    changes={"version": "1.1"},
)
```

Expected results:

- `monitor.status == "monitored"`
- `update.status == "updated"`
- Audit events are appended to `events.jsonl`.

## How Retry Works

Retry is controlled by `RuntimePolicy.retry.max_attempts`.

```python
from runtime_core import RuntimePolicy

policy = RuntimePolicy.with_retry(
    network_mode="OFF",
    local_model="qwen3:8b",
    cloud_model="deepseek-reasoner",
    retry_max_attempts=3,
)
```

If a handler raises an exception:

- Runtime emits `agent_retry` for failed attempts before the final attempt.
- Runtime emits `agent_failed` if all attempts fail.
- Runtime emits `agent_completed` with `attempt` when an attempt succeeds.

Retry does not bypass permissions or lifecycle checks.

## How Sensitive Context Access Works

Normal context:

```python
context = kernel.get_context(
    "body_agent",
    credential="<body-agent-credential>",
    task="core",
)
```

Sensitive context requires an Access Request:

```python
request = kernel.request_access(
    "body_agent",
    resource="05_Domains/Body/core.md",
    reason="Need owner-approved context for a reviewed task.",
    sensitivity="level_3",
)

approved = kernel.approve_access_request(
    request.request_id,
    reviewer="owner",
    reason="Approved for one reviewed task.",
)

context = kernel.get_context_with_access(
    "body_agent",
    credential="<body-agent-credential>",
    task="core",
    access_request_id=approved.request_id,
)
```

Safety rules:

- Pending requests cannot be used.
- Requests cannot be used by a different Agent.
- Approved requests grant one exact `resource` path only.
- The read still goes through Knowledge Gateway.
- Agents still never open Markdown files directly.

## Verification Commands

Run focused Runtime checks:

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest tests/test_runtime_core.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
```

Run Schema + Gateway + Runtime integration checks:

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest tests/test_knowledge_schema.py tests/test_knowledge_gateway.py tests/test_runtime_core.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py -q
```

Run the full suite:

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m pytest -q
```

Compile check:

```powershell
D:\个人混合管理系统\.venv\Scripts\python.exe -m compileall runtime_core knowledge_system config tests/test_runtime_core.py tests/test_runtime_policy.py tests/test_runtime_scheduler.py
```

Whitespace check:

```powershell
git diff --check
```

Current verified result:

```text
340 passed, 3 skipped, 78 subtests passed
```

## Troubleshooting

`AgentLifecycleError("agent_not_active")`

The Agent was registered but not activated, or it was deactivated. Run `kernel.activate_agent(agent_id)` before execution.

`PermissionDenied("*_denied")`

The Agent definition does not include the required runtime permission. Add only the minimum permission needed, such as `read_knowledge`, `propose_change`, or `request_access`.

`AccessRequestDenied("access_request_not_approved")`

The Access Request exists but is still pending or rejected. It must be approved before use.

`AccessRequestDenied("access_request_agent_mismatch")`

The request belongs to another Agent. Create and approve a request for the requesting Agent.

`ValueError("network_mode must be OFF, ASSIST, or SYNC")`

The network config is not one of the frozen modes. Use `OFF` unless a future reviewed phase explicitly enables another mode.

## Design Notes

The Runtime is intentionally conservative.

Agent execution is useful only if it remains governed. That is why Runtime separates registration, activation, execution, monitoring, updates, permissions, model routing, context access, and approval. This is slower than letting an Agent call tools directly, but it creates a system that can be audited and extended safely.

The `runtime_core` package also avoids the existing `runtime/` directory. That directory contains current Personal AI OS runtime state. Keeping code in `runtime_core/` prevents mixing new kernel code with existing operational data.
