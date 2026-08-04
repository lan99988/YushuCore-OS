# Personal Knowledge OS Phase 2 Runtime Core Report

Date: 2026-08-04

Status: Phase 2 minimal runtime slice implemented and verified.

## Scope

This phase starts Personal Agent Runtime without connecting existing BodyOS, StudyOS, Feishu automation, or llm_wiki internals.

Implemented package:

```text
runtime_core/
+-- approval.py
+-- access.py
+-- config.py
+-- context.py
+-- events.py
+-- kernel.py
+-- logger.py
+-- memory.py
+-- models.py
+-- permissions.py
+-- policy.py
+-- registry.py
+-- router.py
+-- scheduler.py
+-- tools.py
```

The existing `runtime/` directory is preserved as runtime state data used by the current Personal AI OS. Code was placed in `runtime_core/` to avoid mixing new Runtime Kernel code with existing operational data.

## Implemented Runtime Services

- Runtime Kernel: registers and executes Agents through one controlled entrypoint.
- Agent Registry: requires explicit Agent registration and supports YAML-backed Agent definitions.
- Agent Scheduler: enforces Register -> Activate -> Execute -> Monitor -> Update -> Deactivate lifecycle gates.
- Permission Manager: checks runtime permissions such as `execute`, `read_knowledge`, `use_tools`, and `propose_change`.
- Knowledge Gateway Client: exposes the Runtime-facing gateway boundary and forwards knowledge calls to the real Knowledge Gateway.
- Context Manager: builds Agent context only through `KnowledgeGatewayClient -> KnowledgeGateway.get_context()` and `KnowledgeGatewayClient -> KnowledgeGateway.get_context_with_access_grant()`.
- Memory Manager: records Agent execution memory in runtime state JSONL.
- Model Router: keeps `OFF` mode local-first, routes complex tasks to cloud only when network mode allows it, forces `level_3`/`level_4` context to local models, and emits auditable model route selection events.
- Runtime Policy: loads `config/network.yaml`, `config/model.yaml`, and `config/runtime.yaml`, with `network_mode: OFF` as the default runtime posture.
- Retry Policy: retries failed Agent execution according to Runtime policy and emits auditable retry events with exception type only, not exception messages.
- Tool Manager: exposes tools through permission-checked runtime calls and emits audit events for allowed, denied, unknown, and failed tool calls without logging tool arguments.
- Approval Engine: delegates Knowledge Change Proposal requests, approvals, rejections, and expirations through `KnowledgeGatewayClient -> Knowledge Gateway`.
- Access Request Store: records high-sensitivity context access requests as pending/approved/used/rejected Runtime state.
- Event Bus and Logger: emit auditable activation, model routing, execution, tool, completion, and failure events without logging raw exception messages or knowledge context bodies.

## Safety Boundaries

- Agents do not read or write Vault files directly.
- Knowledge access flows through Runtime -> Context Manager -> Knowledge Gateway Client -> Knowledge Gateway.
- Knowledge modification flows through Runtime -> Approval Engine -> Knowledge Gateway Client -> Knowledge Gateway -> Proposal/Human Approval.
- Human review outcomes (`approved`, `rejected`, `expired`) are exposed through Runtime so reviewers do not bypass the Runtime/Gateway boundary.
- High-sensitivity access intent is captured as an Access Request before any privileged context read.
- Approved Access Requests grant one exact resource path for one temporary high-sensitivity context read, then become `used`.
- Denied Access Grant attempts emit `access_grant_denied` audit events with the denial reason.
- Default network behavior remains local-first; `OFF` never routes to cloud.
- Cloud routing is blocked when Runtime context contains `level_3` or `level_4` data.
- Model routing decisions emit `model_route_selected` with provider, reason, network mode, complexity, and max context sensitivity, without logging knowledge content.
- Existing BodyOS, StudyOS, Skill system, Feishu integration, llm_wiki, and old notes were not modified.

## Verification

Focused Runtime tests:

```text
tests/test_runtime_core.py
17 passed
```

Runtime policy tests:

```text
tests/test_runtime_policy.py
3 passed
```

Runtime scheduler tests:

```text
tests/test_runtime_scheduler.py
3 passed
```

Runtime Gateway Client tests:

```text
tests/test_runtime_gateway_client.py
3 passed
```

Schema + Gateway + Runtime integration:

```text
56 passed
```

Full test suite:

```text
344 passed, 3 skipped, 78 subtests passed
```

## Next Phase 2 Work

- Runtime operation guide: `07_系统文档（Docs）/Runtime_Core_Operation_Guide.md`
