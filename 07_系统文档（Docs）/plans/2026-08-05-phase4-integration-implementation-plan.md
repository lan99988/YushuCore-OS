# Phase 4 Integration and Agent Expansion Implementation Plan

**Goal:** 在不破坏 Phase 3 冻结契约的前提下，实现 Phase 4 Integration Adapter、统一 Agent 输入输出协议、Agent 协作事件、Knowledge Agent 完整流水线和未来 Agent 的可注册骨架。

**Architecture:** 外部系统只通过 Integration Adapter Layer 进入 Personal Agent Runtime；Runtime 再通过 Permission、Memory、Model Router、Tool 和 Gateway 访问资源。写入和外部执行始终使用 Proposal / Approval，默认网络模式保持 `OFF`。

**Tech Stack:** Python、dataclasses、pytest、现有 Runtime Kernel、EventBus、Knowledge Gateway、Approval Engine、JSONL 状态存储。

---

### Task 1: 冻结并扩展统一 Agent 协议

**Files:**
- Modify: `runtime_core/models.py`
- Modify: `agents/sdk.py`
- Modify: `runtime_core/permissions.py`
- Create: `tests/test_phase4_agent_protocol.py`

- [x] 添加 `AgentRequest`、`AgentResult`、`AutonomyLevel` 和标准输入输出字段。
- [x] 为 `AgentSDK` 增加 `request()`、`response_from_request()` 和来源/动作序列化能力。
- [x] 增加权限矩阵检查：知识读取、认知分析、执行、修改必须区分。
- [x] 测试无权限、需要申请和已授权三种结果。

### Task 2: 实现 Integration Adapter Layer

**Files:**
- Create: `integrations/base.py`
- Create: `integrations/obsidian.py`
- Create: `integrations/llm_wiki.py`
- Create: `integrations/feishu.py`
- Create: `integrations/__init__.py`
- Create: `tests/test_phase4_integrations.py`

- [x] 定义 Adapter 统一接口、网络模式门禁、correlation id 和错误归一化。
- [x] Obsidian 只提供 Markdown/YAML 读写 Proposal 与 Git 回滚接口。
- [x] llm_wiki 只提供 search/read_context/get_schema/health，不修改 exe、不提供写文件工具。
- [x] Feishu 只接受已批准 Proposal，支持幂等键、提交状态和失败恢复。
- [x] 测试三个 Adapter 都不能直接拿到 Vault、Memory 或 Runtime Core。

### Task 3: 完善 Knowledge Agent 流水线

**Files:**
- Modify: `agents/knowledge_pipeline.py`
- Modify: `agents/knowledge.py`
- Create: `tests/test_phase4_knowledge_pipeline.py`

- [x] 增加 Importer、Reviewer、Knowledge Auditor。
- [x] 统一 `capture_item` 输入与 Markdown/YAML 输出。
- [x] 增加失效链接、过时知识、冲突观点检测。
- [x] 所有整理动作只输出 Proposal。

### Task 4: 实现 Agent 协作与未来 Agent 注册骨架

**Files:**
- Create: `runtime_core/collaboration.py`
- Modify: `runtime_core/events.py`
- Modify: `agents/registry.yaml`
- Create: `agents/future.py`
- Create: `tests/test_phase4_collaboration.py`

- [x] 通过 EventBus 发布和订阅 Agent 事件，禁止 Agent 直接调用其他 Agent。
- [x] 实现 `body_low_energy` 事件的标准载荷和订阅入口。
- [x] 注册 Health、Research、File、Calendar、Communication Agent 的安全骨架。
- [x] 未来 Agent 默认不激活，且不获得越权权限。

### Task 5: 安全加固、文档和全量验证

**Files:**
- Create: `runtime_core/integration_policy.py`
- Modify: `runtime_core/kernel.py`
- Modify: `07_系统文档（Docs）/Phase_4_Integration_Technical_Design_Review.md`
- Create: `tests/test_phase4_security.py`

- [x] 统一 OFF/ASSIST/SYNC 策略并记录审计事件。
- [x] 对外部 Adapter 调用增加 fail-closed、超时、幂等和回滚策略。
- [x] 将最终实现状态、测试结果和剩余限制写入 Review 文档。
- [x] 运行 `pytest -q`、Boundary Validator、`compileall` 和 `git diff --check`。
