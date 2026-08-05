# Phase 3 Technical Design

Version: v0.1
Date: 2026-08-05
Status: Design Draft / Approved to Begin Phase 3
Depends on: `phase2-runtime-accepted-v1.0`

## 1. Phase 3 目标

Phase 3 的目标是实现第一批 Specialized Agents，但不得重构 Phase 2 Runtime Core。

优先级：

1. Knowledge Agent
2. Body Agent
3. Study Agent
4. Project Agent

所有 Agent 必须通过 Runtime 注册、激活、执行、审计。Agent 不直接访问 Vault，不直接调用外部 API，不直接写 Markdown。

## 2. Phase 3 总体结构

建议新增目录：

```text
agents/
├── __init__.py
├── sdk.py
├── registry.py
├── knowledge_agent/
│   ├── __init__.py
│   ├── definition.py
│   ├── handler.py
│   └── prompts.py
├── body_agent/
│   ├── __init__.py
│   ├── definition.py
│   └── handler.py
├── study_agent/
│   ├── __init__.py
│   ├── definition.py
│   └── handler.py
└── project_agent/
    ├── __init__.py
    ├── definition.py
    └── handler.py

skills/
└── interfaces.py
```

本设计只允许新增 Agent 层目录；不得改变 `runtime_core/` 目录结构。

## 3. Agent Registry 设计

Phase 3 的 Agent Registry 是 Runtime Registry 的上层装配器，不替代 `runtime_core.registry.AgentRegistry`。

职责：

- 收集各 Agent 的 `AgentDefinition`。
- 为 RuntimeKernel 批量注册 Agent。
- 保持 Agent identity 唯一。
- 不持有 Vault 路径。
- 不绕过 RuntimeKernel。

建议接口：

```python
def get_phase3_agent_definitions() -> list[AgentDefinition]:
    return [
        knowledge_agent_definition(),
        body_agent_definition(),
        study_agent_definition(),
        project_agent_definition(),
    ]

def register_phase3_agents(kernel: RuntimeKernel) -> None:
    for definition in get_phase3_agent_definitions():
        kernel.register_agent(definition)
```

约束：

- Agent 注册必须失败快，不允许重复 `agent_id`。
- Agent Definition 的权限必须显式列出。
- 注册层不得执行 Agent 业务逻辑。

## 4. Knowledge Agent 架构

定位：

Knowledge Agent 是 Phase 3 的第一个核心 Agent。它负责知识生命周期中的分析、整理、提议和路由，但不直接写 Vault。

建议身份：

```python
AgentDefinition(
    agent_id="knowledge_agent",
    name="Knowledge Agent",
    domain="knowledge",
    autonomy_level=2,
    risk_level="medium",
    permissions=(
        "execute",
        "read_knowledge",
        "propose_change",
        "request_access",
        "use_tools",
    ),
    handler=knowledge_agent_handler,
)
```

内部能力模块：

```text
Collector
Importer
Analyzer
Schema Generator
Reviewer
Router
Librarian
```

Phase 3 v1 范围：

- 分析 RuntimeContext 中授权知识。
- 生成结构化 Proposal。
- 调用受控工具做本地摘要或分类。
- 生成审计友好的输出。

禁止：

- 直接扫描 `D:\Personal_Knowledge_Vault`。
- 直接移动旧笔记。
- 直接写 Markdown。
- 直接调用网络。

## 5. Body Agent 架构

定位：

Body Agent 连接既有 BodyOS，但不能重建 BodyOS，也不能绕过 Runtime。

建议身份：

```python
AgentDefinition(
    agent_id="body_agent",
    name="Body Agent",
    domain="body",
    autonomy_level=2,
    risk_level="medium",
    permissions=(
        "execute",
        "read_knowledge",
        "propose_change",
        "use_tools",
    ),
    handler=body_agent_handler,
)
```

职责：

- 读取授权的 body domain 知识。
- 结合 Runtime Memory 理解近期反馈。
- 生成训练、恢复、睡眠、营养相关建议。
- 对需要沉淀的经验生成 Proposal。

禁止：

- 直接读取 Garmin/JWT 辅助脚本输出作为隐式事实源。
- 自动修改训练原则。
- 自动写入健康原则。

## 6. Study Agent 架构

定位：

Study Agent 连接学习系统，负责学习策略、复盘、计划建议与知识提议。

建议身份：

```python
AgentDefinition(
    agent_id="study_agent",
    name="Study Agent",
    domain="study",
    autonomy_level=2,
    risk_level="medium",
    permissions=(
        "execute",
        "read_knowledge",
        "propose_change",
        "request_access",
    ),
    handler=study_agent_handler,
)
```

职责：

- 读取 study domain 知识与原则。
- 分析学习方法、错题复盘、计划执行反馈。
- 对学习原则变化生成 Proposal。

禁止：

- 直接改写 `03_Principles/study`。
- 访问 Self Model / level_4 数据，除非 Human Approval 给出临时授权。

## 7. Project Agent 架构

定位：

Project Agent 连接项目知识与执行系统，但 Phase 3 不直接做 Feishu 深度集成。

建议身份：

```python
AgentDefinition(
    agent_id="project_agent",
    name="Project Agent",
    domain="project",
    autonomy_level=2,
    risk_level="medium",
    permissions=(
        "execute",
        "read_knowledge",
        "propose_change",
        "use_tools",
    ),
    handler=project_agent_handler,
)
```

职责：

- 读取 project domain 知识。
- 生成项目状态摘要。
- 发现决策记录缺口。
- 对项目知识更新生成 Proposal。

禁止：

- 直接创建 Feishu 任务。
- 自动变更项目优先级。
- 绕过 Human Approval 进入执行系统。

## 8. Agent SDK

Agent SDK 是轻量封装层，不改变 Runtime API。

目标：

- 降低 AgentDefinition 重复代码。
- 提供统一 handler 输入/输出约定。
- 提供受控 Proposal helper。
- 提供标准审计友好输出结构。

建议结构：

```python
@dataclass(frozen=True)
class AgentResponse:
    summary: str
    findings: list[str]
    proposals: list[dict]
    next_actions: list[str]

def make_agent_definition(... ) -> AgentDefinition:
    ...
```

约束：

- SDK 只能调用 Runtime 公共 API。
- SDK 不持有 Vault 路径。
- SDK 不绕过 Tool Manager。
- SDK 不绕过 Approval Engine。

## 9. Skill 接口

Skill 在 Phase 3 中暂定位为 Agent 能力描述与受控工具桥接，不直接成为自治执行系统。

建议接口：

```python
@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    domain: str
    required_permissions: tuple[str, ...]
    risk_level: str
```

调用关系：

```text
Agent handler
-> RuntimeContext.tools.call(skill_tool_name, ...)
-> ToolManager
-> PermissionManager
-> registered skill adapter
-> audit event
```

禁止：

- Skill 直接打开 Vault。
- Skill 直接调用外部 API。
- Skill 直接写入 Markdown。

## 10. Runtime 与 Agent 的调用关系

标准调用：

```text
User / System Task
-> RuntimeKernel.execute(agent_id, credential, task)
-> Scheduler active check
-> Permission check: execute
-> ContextManager
-> KnowledgeGatewayClient
-> ModelRouter
-> RuntimeContext
-> Agent handler
-> ToolManager / ApprovalEngine / MemoryManager as needed
-> RuntimeResult
-> EventBus / RuntimeLogger
```

知识修改：

```text
Agent finding
-> RuntimeKernel.request_update()
-> Permission check: propose_change
-> KnowledgeGatewayClient.request_update()
-> Proposal pending
-> Human Review
-> approve / reject / expire
-> Gateway applies approved change
```

高敏访问：

```text
Agent needs level_3 / level_4 context
-> RuntimeKernel.request_access()
-> Human Review
-> RuntimeKernel.get_context_with_access()
-> one-time access
-> local model forced
```

## 11. Phase 3 风险分析

| Risk | Impact | Control |
|---|---|---|
| Agent 绕过 Runtime 直接读写文件 | 破坏 Markdown First 与审计边界 | 代码审查、测试、禁止文件路径入口 |
| Agent 权限过大 | 形成万能 Agent | 最小权限、AgentDefinition 审查 |
| Proposal 写入敏感正文到日志 | 泄露个人认知数据 | 复用 Runtime 脱敏审计规则 |
| Body/Study/Project 重建既有系统 | 架构重复和资产破坏 | Agent 只做接入，不替换 |
| 云端模型接触 level_3/level_4 | 高敏数据泄露 | ModelRouter 强制本地 |
| Phase 3 修改 Runtime API | 破坏冻结契约 | Proposal -> Review -> Approval -> Migration |
| 旧笔记被自动迁移 | 迁移污染 | Phase 3 禁止旧笔记迁移 |
| Tool 直接调用外部 API | 绕过网络治理 | 所有工具必须注册到 ToolManager |

## 12. Phase 3 验收标准

Phase 3 v1 至少需要：

- Knowledge Agent 可注册、激活、执行。
- Body Agent / Study Agent / Project Agent 至少完成基础定义与受控执行骨架。
- 所有 Agent 只接收 RuntimeContext。
- 所有 Agent 无直接 Vault 文件访问。
- 知识修改只生成 Proposal。
- 工具调用只通过 RuntimeContext.tools。
- 新增 Agent 行为有测试。
- Runtime API 无破坏性变更。

## 13. Phase 3 禁止事项

未经 Human Owner 单独批准，Phase 3 禁止：

- 重构 Runtime Core。
- 修改 Runtime API。
- 改变 Runtime 目录结构。
- 引入破坏兼容性的 Runtime 改动。
- 修改 `llm_wiki.exe`。
- 迁移旧笔记。
- 自动修改个人原则。
- 默认联网。
- Agent 直接访问 Vault。
- Agent 直接调用外部 API。
