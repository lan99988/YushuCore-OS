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
+-- registry.py
+-- router.py
+-- scheduler.py
+-- tools.py
```

The existing `runtime/` directory is preserved as runtime state data used by the current Personal AI OS. Code was placed in `runtime_core/` to avoid mixing new Runtime Kernel code with existing operational data.

## Implemented Runtime Services

- Runtime Kernel: registers and executes Agents through one controlled entrypoint.
- Agent Registry: requires explicit Agent registration and supports YAML-backed Agent definitions.
- Agent Scheduler: enforces Register -> Activate -> Execute -> Deactivate lifecycle gates.
- Permission Manager: checks runtime permissions such as `execute`, `read_knowledge`, `use_tools`, and `propose_change`.
- Context Manager: builds Agent context only through `KnowledgeGateway.get_context()`.
- Memory Manager: records Agent execution memory in runtime state JSONL.
- Model Router: keeps `OFF` mode local-first and routes complex tasks to cloud only when network mode allows it.
- Tool Manager: exposes tools through permission-checked runtime calls.
- Approval Engine: delegates Knowledge Change Proposal requests and approvals to Knowledge Gateway.
- Access Request Store: records high-sensitivity context access requests as pending/approved/rejected Runtime state.
- Event Bus and Logger: emit auditable activation, execution, completion, and failure events.

## Safety Boundaries

- Agents do not read or write Vault files directly.
- Knowledge access flows through Runtime -> Context Manager -> Knowledge Gateway.
- Knowledge modification flows through Runtime -> Approval Engine -> Knowledge Gateway -> Proposal/Human Approval.
- High-sensitivity access intent is captured as an Access Request before any future privileged context read.
- Default network behavior remains local-first; `OFF` never routes to cloud.
- Existing BodyOS, StudyOS, Skill system, Feishu integration, llm_wiki, and old notes were not modified.

## Verification

Focused Runtime tests:

```text
tests/test_runtime_core.py
8 passed
```

Schema + Gateway + Runtime integration:

```text
37 passed
```

Full test suite:

```text
325 passed, 3 skipped, 78 subtests passed
```

## Next Phase 2 Work

- Add stricter Runtime policy files under `config/`.
- Add Scheduler monitor/update state transitions and retry policy.
- Connect approved Access Requests to temporary high-sensitivity context grants.
- Add Runtime operation docs after the policy format is stable.
