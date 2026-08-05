# Phase 3 Agent System Final Architecture Report

日期：2026-08-05
状态：Phase 3.5 Accepted

## Agent架构

Agent 系统的最终落点是“Agent 只做决策与提案，Runtime 负责约束、路由、审计和落地”。

### Agent SDK最终结构

`agents.sdk` 当前提供四个核心对象：

- `AgentSDK`
- `AgentResponse`
- `SkillSpec`
- `make_agent_definition`

其中 `AgentResponse` 是统一返回体，包含：

- `summary`
- `findings`
- `proposals`
- `next_actions`
- `skills`
- `reason`
- `evidence`
- `confidence`
- `governance`

`AgentSDK` 只负责构造响应与 Proposal，不直接访问文件系统、Vault 或外部执行接口。

### Agent Registry设计

Agent 注册由 `runtime_core.registry.AgentRegistry` 承担，Phase 3 的默认定义由 `agents.registry.yaml` 和 `agents.__init__` 里的导出入口串联。

当前四个核心 Agent 为：

- `knowledge_agent`
- `body_agent`
- `study_agent`
- `project_agent`

注册表规则很简单：

- `agent_id` 唯一
- 先注册，后激活
- 通过 `agent_id` 查询定义
- 由 Runtime Scheduler 管理激活状态

### Agent Governance机制

治理信息由 `runtime_core.models.AgentGovernance` 承载，并在 `RuntimeKernel.execute()` 完成后附加到输出。

字段包括：

- `agent_id`
- `permissions`
- `can_access`
- `cannot_access`
- `tools_called`
- `audit_recorded`

这意味着 Agent 的最终输出不只是业务结果，也携带可审计的治理证据。

### Agent生命周期

标准生命周期如下：

1. Register
2. Activate
3. Build Runtime Context
4. Route Model
5. Execute Handler
6. Attach Governance
7. Record Memory
8. Emit Events
9. Submit Proposal or Return Result

生命周期中，权限和上下文都由 Runtime 统一注入，Agent 自身不持有越界能力。

### Agent调用流程

```text
Agent
↓
Runtime Kernel
↓
Permission Manager
↓
Memory
↓
Model Router
↓
Tool
↓
Resource
```

实际调用链由 `RuntimeKernel.execute()` 组织：

- Registry 找到 Agent
- Scheduler 确认激活
- Permission Manager 检查权限
- Context Manager 通过 Gateway 构建上下文
- Model Router 决定本地或云模型
- ToolManager 绑定受控工具
- Handler 执行
- Governance 追加
- Memory 记录
- EventBus / Logger 记账

## 四大核心Agent

### Knowledge Agent

Knowledge Agent 是基础 Agent，负责知识进入、分析、整理和提案。

#### Collector

输入：

- PDF
- 网页
- AI 聊天
- 微信
- 视频
- 手工输入

处理：

- `capture`
- 进入 `00_Inbox`

输出：

- `CaptureCandidate`

#### Analyzer

处理原始资料，输出：

- 摘要
- 关键词
- 主题
- 关联知识
- 分类建议

#### Schema Generator

生成 Markdown Metadata 草案，包含：

- `id`
- `type`
- `domain`
- `source`
- `confidence`
- `status`
- `agent_access`
- `created`
- `updated`

#### Librarian

负责发现：

- 重复知识
- 孤立知识
- 知识冲突

但只能输出 Proposal，不能自动修改。

权限边界：

- 允许读知识上下文
- 允许提出提案
- 禁止直接写 Vault
- 禁止直接改 Markdown

### Body Agent

Body Agent 连接现有 BodyOS，但不重写 BodyOS。

#### BodyOS Tool接口

Body Agent 通过受控工具 `body_os.read_snapshot` 读取：

- 身体数据
- 训练记录
- 恢复状态

#### Training Load Proposal流程

当训练量连续增加且恢复下降时，Body Agent 生成训练负荷调整 Proposal。

当前输出保持为：

- `proposal_type: training_adjustment`
- `recommended_load: reduce | maintain`
- `requires_human_review: true`
- `status: draft`

权限边界：

- 允许读取受控 BodyOS snapshot
- 允许提出训练建议
- 禁止自动修改训练计划

### Study Agent

Study Agent 负责学习系统。

#### Learning Map

把学习目标与知识点整理成知识地图。

#### Learning Path

把知识地图展开为学习路径和执行顺序。

#### Review Recommendation

生成复习建议，推动复习与巩固。

当前实现会基于 Runtime 提供的知识上下文和任务，输出：

- `knowledge_map`
- `learning_path`
- `review_suggestions`

权限边界：

- 允许读取学习相关知识上下文
- 允许提出学习建议
- 禁止自动改学习资料

### Project Agent

Project Agent 负责项目执行建议，不直接执行外部任务。

#### Feishu Task Proposal流程

当前链路是：

```text
Project Agent
↓
Task Proposal
↓
Execution Gateway
↓
Feishu
```

但在 Phase 3.5，实际实现只停在 Proposal：

- `status: pending_human_review`
- `execution_gateway: feishu`
- `executed: false`

权限边界：

- 允许生成项目提案
- 允许携带知识证据
- 禁止直接调用 Feishu

## Runtime关系

Runtime 是 Agent 体系的中心，不是附件。

```text
Agent
↓
Runtime
↓
Permission
↓
Memory
↓
Model Router
↓
Tool
↓
Resource
```

补充关系：

- `ContextManager` 通过 Gateway 提供知识上下文
- `PermissionManager` 只允许授权动作
- `ModelRouter` 依据复杂度、网络模式和上下文敏感度选择模型
- `ToolManager` 记录工具调用
- `MemoryManager` 保存运行记忆

这套关系保证 Agent 只能在 Runtime 许可的范围内行动。

## Memory模型

Phase 3.5 采用三层 Memory：

- `System Memory`：`99_System`
- `Agent Memory`：`08_Agent_Memory`
- `Personal Memory`：`11_Self_Model`

规则很明确：

- System Memory 放系统规则
- Agent Memory 放 Agent 经验
- Personal Memory 放个人经验

并且：

- Agent 禁止写入 `Personal Memory`
- `runtime_core.memory.MemoryManager.record(scope="personal")` 会直接拒绝

## Security Boundary

Phase 3.5 的安全边界可以收束为五条：

- 禁止直接访问 Vault
- 禁止直接修改 Markdown
- 禁止绕过 Gateway
- 所有变更必须走 Proposal 机制
- 所有关键动作必须进入 Audit 机制

这也是 Phase 3.5 为什么只允许“提案”和“解释”，不允许“直接写入”和“直接执行”。

## 冻结声明

Phase 3 API 与 Agent Contract 已冻结。后续进入 Phase 4 以后，除非满足：

Proposal -> Review -> Approval -> Migration

否则禁止修改：

- `Agent SDK`
- `Runtime API`
- `Permission Contract`
- `Memory Contract`
