# Yushu-OS 下一阶段总执行计划

> **交给执行型 AI：** 必须按工作包顺序执行；每次只领取一个工作包。推荐使用 executing-plans 类流程逐项勾选。未经上一工作包验收，不得开始下一工作包。

**目标：** 在不推翻现有稳定系统的前提下，把 Yushu-OS 演进为“前端六条用户逻辑链 + 核心认知与治理 + 编排层 + 后端能力插件 + 联邦式事实源”的个人自适应 AI 操作系统。

**架构：** 采用 Strangler Migration（绞杀者迁移）和纵向切片。先冻结契约与安全边界，再建立插件注册和编排骨架；随后用 Capture → Today → Adjust 打通首个完整闭环，最后迁移其余逻辑链与领域插件。旧入口在新链路具备行为等价、自动化测试和回滚路径前不得删除。

**技术栈：** Python 3.11+、pytest、PyYAML、dataclass、SQLite、飞书 Base/任务/日历、D:\Knowledge、IMA、本地 Garmin 数据、现有 runtime_core / information_system / cognitive_system / knowledge_system / personal_intelligence。

---

## 1. 计划定位

这不是一个要求单个 AI 一次性完成的“大任务”，而是一组可独立执行、独立测试、独立验收、独立回滚的工作包。

执行关系：

~~~text
WP0 基线与治理冻结
  ↓
WP1 能力插件契约与注册中心
  ↓
WP2 自治策略与审计统一
  ↓
WP3 编排层骨架
  ↓
WP4 第一批核心插件适配
  ↓
WP5 Capture / Today / Adjust 纵向闭环
  ↓
WP6 Plan / Review / Explore
  ↓
WP7 个人领域插件
  ↓
WP8 Personal Intelligence 闭环
  ↓
WP9 可观测性、恢复与迁移收口
  ↓
WP10 总验收与版本冻结
~~~

并行规则：

- WP0–WP5 严格串行。
- WP6 验收通过后，WP7 的不同领域插件可以分支并行，但不得同时修改公共契约。
- WP8 依赖至少 Capture、Today、Adjust、Review 四条逻辑链稳定。
- WP9 可以在 WP6 后开始补充观测，但最终验收必须等待 WP7、WP8 完成。
- 每个工作包由执行 AI 提交实现证据；验收 AI 只审查，不替执行 AI 隐式补代码。

## 2. 当前真实基线

计划制定日：2026-09-26。

已验证：

- 全量测试：424 passed，47 subtests passed。
- scripts/verify.py：退出码 0。
- Python 最低版本：3.11。
- 全局网络默认：OFF。
- 现有 Agent 自治等级：Level 2。
- 已存在 runtime_core、knowledge_system、information_system、cognitive_system、personal_intelligence、agents、integrations。
- information_system 已具备信息对象、领域注册、识别报告、生命周期和 SQLite 投影。
- knowledge_system 已具备 Gateway、Proposal、Review、Approval、Write 边界。
- 工作区当前存在大量未提交改动；执行 AI 不得重置、覆盖或顺手提交这些改动。

基线命令：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify.py
git diff --check
git status --short
~~~

任何工作包开始前都要记录以上命令结果。若基线失败，先停止并报告，不得把原有失败归因于本工作包。

## 3. 已冻结的产品决定

### 3.1 顶层使命

Yushu-OS 服务的是用户本人和用户希望达到的更好状态，不是单独服务任务、日历或知识条目。

系统主链：

~~~text
信息 → 理解 → 关系 → 判断 → 决策 → 行动 → 结果 → 学习
~~~

最高设计原则：消除模糊，并降低维护阻力。

### 3.2 前端按六条逻辑链组织

用户只面对：

- Capture：发生了一件事。
- Plan：我要实现一个目标。
- Today：我今天应该怎么过。
- Adjust：情况发生变化。
- Review：最近怎么样。
- Explore：帮我理解一个问题。

本阶段的“前端”指 WorkBuddy/对话/API 的用户交互层，不新建 Web GUI。任何图形界面属于后续独立项目。

### 3.3 后端按能力插件组织

插件回答“系统能做什么”，不回答“用户最终应该怎么做”。最终决策由编排层结合目标、约束、上下文和权限完成。

Skill 与 Plugin 严格区分：

- Skill：告诉 AI 何时、如何使用能力。
- Plugin：真正提供可调用、可测试、可审计的能力。

### 3.4 不做大爆炸重构

现有输入解析、Agent、Runtime、信息层、知识网关和飞书写入路径均保留。新路径先以适配器包围旧路径；完成行为等价测试后才允许废弃旧入口。

### 3.5 联邦式事实源

不再使用“所有数据必须进入同一个数据库”的假设。

| 数据 | 权威事实源 |
|---|---|
| 任务、日历、项目执行态、承诺、需移动端触达的状态 | 飞书 |
| 知识正文、经验、方法、原则、项目认知态 | D:\Knowledge，经 Knowledge Gateway |
| 信息对象结构化投影、识别状态、领域观察 | 本地 SQLite information_system |
| 身体原始数据 | Garmin / Body Dataset |
| 系统配置与插件清单 | 本地版本化配置 |
| 代码与架构版本 | Git |
| 财务 | 月度快照，不保存逐笔流水 |

### 3.6 自治语义

聊天中定义的 L0–L3 是“动作权限等级”，不等同于现有 AgentDefinition.autonomy_level。

- Observe：只读分析。
- Suggest：给建议，不执行。
- Autonomous：仅限可恢复、内部、低风险、无外部承诺的动作。
- Approval Required：外部承诺、支付、消息发送、固定会议、强制截止、不可逆操作、重大删除。

现有 Agent 自治上限继续保持 Level 2。Approval Required 表示走审批闸门，不表示把 Agent 提升为 autonomy_level=3。

## 4. 明确不在本轮范围

- 不整体上云；ADR-007 仍是 Proposed，本计划不把 platform 改为 hybrid_runtime。
- 不训练 LoRA、Fine-tune 或可自动改写用户人格的模型。
- 不允许 Agent 直接访问 Vault 文件或直接调用外部 API。
- 不把 Finance 扩展为逐笔账本、预算、投资或资产管理。
- 不为 Social 建高维护成本的完整联系人数据库。
- 不预建用户当前尚未涉及的 Life Administration 子领域。
- 不在 Interest 中引入 KPI、连续打卡或强制任务化。
- 不删除 input_parser_old.py 或现有 handler。
- 不新增未经用户确认的一级领域。
- 不把 IMA 当业务数据库或知识事实源。

## 5. 目标代码映射

| 概念层 | 复用/新增位置 | 职责 |
|---|---|---|
| Experience Layer | 新增 experience_layer/ | 六条逻辑链的统一输入输出，不接触具体存储 |
| Cognitive Core | 复用 runtime_core、cognitive_system、personal_intelligence | 身份、目标、约束、权限、个人规则、审计 |
| Orchestration Layer | 新增 orchestration/ | 意图、流程、能力计划、策略检查、执行 |
| Capability Plugin Layer | 新增 capability_plugins/ | 插件契约、注册、生命周期、领域适配器 |
| Data / Integration Layer | 复用 information_system、knowledge_system、integrations、飞书引擎 | 事实源访问和外部连接 |

禁止新增第二套 Runtime、第二套 Knowledge Gateway、第二套信息对象数据库或绕过现有飞书 Processor 的写入口。

## 6. 执行纪律

### 6.1 分支与工作区

- 当前工作区不干净。执行前必须由用户明确选择一个已保存的起点。
- 推荐从用户确认的提交创建独立 worktree，分支名使用 codex/yushu-wpXX-名称。
- 不得使用 git reset --hard、git checkout -- 或清理未跟踪文件。
- 一个工作包一个分支；验收通过后再合并。
- 一个提交只表达一个可审查意图。

### 6.2 TDD 顺序

每个行为变更必须遵循：

1. 写一个失败测试。
2. 运行单测并确认失败原因正确。
3. 写最小实现。
4. 运行目标测试。
5. 运行相关模块测试。
6. 运行全量测试和 scripts/verify.py。
7. 提交。

### 6.3 每个工作包必须交付的证据

执行 AI 的最终回复和验收报告必须包含：

- 分支名与提交 SHA。
- git diff --stat。
- 新增/修改文件清单。
- 目标测试命令与完整结果摘要。
- 全量测试结果。
- scripts/verify.py 结果。
- 手工场景结果。
- 新增风险与回滚方式。
- 是否发生外部写入；若发生，附审批证据和写入对象。
- 未完成项必须明确列出，不得用“基本完成”代替。

验收报告保存到：

~~~text
07_系统文档（Docs）/验收/WPXX-验收报告.md
~~~

## 7. WP0：基线与治理冻结

**目标：** 把新总纲固化为无歧义、机器可验证的架构边界；不改变运行行为。

**依赖：** 无。

**文件：**

- 新建：07_系统文档（Docs）/PROJECT_CHARTER.md
- 新建：07_系统文档（Docs）/ARCHITECTURE_V2.md
- 新建：07_系统文档（Docs）/PLUGIN_STANDARD.md
- 新建：07_系统文档（Docs）/AUTONOMY_POLICY.md
- 新建：07_系统文档（Docs）/DOMAIN_REGISTRY.md
- 新建：07_系统文档（Docs）/ADR/ADR-010_Experience_Orchestration_Plugin_Architecture.md
- 修改：07_系统文档（Docs）/SYSTEM_BLUEPRINT.md
- 修改：07_系统文档（Docs）/DECISION_LOG.md
- 修改：README.md
- 新建：tests/test_architecture_contracts.py

### Task 0.1：记录干净的验收起点

- [ ] 运行四条基线命令并把结果写入 WP0 验收报告。
- [ ] 记录当前 HEAD、Python 版本和配置摘要。
- [ ] 确认没有修改用户已有未提交文件。

### Task 0.2：冻结五层映射与六条逻辑链

- [ ] PROJECT_CHARTER.md 只描述使命、用户价值、范围和非目标。
- [ ] ARCHITECTURE_V2.md 明确五层依赖方向，只允许上层调用下层公开接口。
- [ ] ADR-010 明确采用渐进迁移，以及不新建平行 Runtime/Gateway。
- [ ] SYSTEM_BLUEPRINT.md 标记旧“飞书唯一事实源”表述已被联邦式事实源裁决取代。
- [ ] DECISION_LOG.md 增加新决策，并保留旧决策的历史文本，不静默改写历史。

### Task 0.3：冻结插件与自治文档

- [ ] PLUGIN_STANDARD.md 定义插件字段、调用合同、错误、审计和生命周期。
- [ ] AUTONOMY_POLICY.md 明确动作权限与 Agent 自治等级的区别。
- [ ] DOMAIN_REGISTRY.md 列出现有一级领域和激活策略。
- [ ] Social、Finance、Life Admin、Creation、Interest、Experience 的低摩擦原则写入领域文档。

### Task 0.4：添加文档契约测试

测试至少断言：

~~~python
def test_architecture_documents_exist():
    required = {
        "PROJECT_CHARTER.md",
        "ARCHITECTURE_V2.md",
        "PLUGIN_STANDARD.md",
        "AUTONOMY_POLICY.md",
        "DOMAIN_REGISTRY.md",
    }
    assert required <= {path.name for path in DOCS.iterdir()}

def test_network_default_remains_off():
    config = yaml.safe_load((ROOT / "config" / "network.yaml").read_text(encoding="utf-8"))
    assert config["network_mode"] == "OFF"

def test_default_autonomy_does_not_exceed_two():
    config = yaml.safe_load((ROOT / "config" / "system.yaml").read_text(encoding="utf-8"))
    assert config["default_autonomy_level"] <= 2
~~~

运行：

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests\test_architecture_contracts.py -q
~~~

**WP0 完成门槛：**

- 文档之间不存在事实源、权限或层级矛盾。
- 没有运行时代码变化。
- 全量测试仍为至少 424 passed、47 subtests passed。

## 8. WP1：能力插件契约与注册中心

**目标：** 让系统可以回答“我有哪些能力、状态如何、需要什么权限、读写什么”。

**依赖：** WP0 验收通过。

**文件：**

- 新建：capability_plugins/__init__.py
- 新建：capability_plugins/contracts.py
- 新建：capability_plugins/manifest.py
- 新建：capability_plugins/registry.py
- 新建：capability_plugins/lifecycle.py
- 新建：capability_plugins/loader.py
- 新建：capability_plugins/manifests/
- 新建：tests/test_capability_contracts.py
- 新建：tests/test_capability_registry.py
- 修改：scripts/verify.py

### 8.1 插件模型

不要把 Installed、Enabled、Active 混为同一状态。采用三个正交维度：

~~~python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

class Availability(str, Enum):
    INSTALLED = "installed"
    UNAVAILABLE = "unavailable"
    ARCHIVED = "archived"

class ActivationState(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    purpose: str
    provides: tuple[str, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    dependencies: tuple[str, ...]
    permissions: tuple[str, ...]
    risk_level: RiskLevel
    activation_mode: str
    availability: Availability = Availability.INSTALLED
    enabled: bool = True
    activation_state: ActivationState = ActivationState.DORMANT
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    error_policy: dict[str, Any] = field(default_factory=dict)
    audit_policy: dict[str, Any] = field(default_factory=dict)

class CapabilityPlugin(Protocol):
    manifest: PluginManifest
    def invoke(self, capability: str, payload: dict[str, Any], context: Any) -> Any:
        raise NotImplementedError
~~~

### 8.2 注册中心行为

注册中心必须支持：

- 重复 plugin_id 拒绝。
- 重复 capability 提供者必须显式设置优先级，否则拒绝。
- 依赖不存在时报错。
- disabled、dormant、unavailable、archived 分别给出可解释错误。
- 按 capability、plugin_id、domain 查询。
- 只返回 manifest，不泄露实现内部。
- 注册和状态切换发出审计事件。

### 8.3 Manifest 加载

Manifest 使用 YAML；加载时拒绝未知字段和缺失字段。首批只登记现有能力，不迁移实现：

- task
- calendar
- project
- goal
- learning
- knowledge
- body
- information

Social、Finance 等第二批插件在 WP7 登记。

### 8.4 测试

核心测试名：

~~~text
test_manifest_rejects_empty_plugin_id
test_manifest_rejects_unknown_risk_level
test_registry_rejects_duplicate_plugin
test_registry_rejects_ambiguous_capability_provider
test_registry_explains_dormant_plugin
test_registry_lists_only_enabled_capabilities
test_loader_rejects_unknown_manifest_field
test_dependency_validation_reports_missing_plugin
~~~

运行：

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests\test_capability_contracts.py tests\test_capability_registry.py -q
.\.venv\Scripts\python.exe scripts\verify.py
~~~

**WP1 完成门槛：**

- registry 能从 YAML 构建确定性能力清单。
- 现有功能行为无变化。
- scripts/verify.py 已编译和检查新包。

## 9. WP2：自治策略与统一审计

**目标：** 对每个计划动作统一做“能否执行、是否要审批、为什么”的判断。

**依赖：** WP1。

**文件：**

- 新建：runtime_core/action_policy.py
- 新建：runtime_core/audit.py
- 修改：runtime_core/models.py
- 修改：runtime_core/kernel.py
- 修改：runtime_core/events.py
- 修改：config/permission.yaml
- 新建：tests/test_action_policy.py
- 修改：tests/test_runtime_core.py

### 9.1 动作策略合同

~~~python
from dataclasses import dataclass
from enum import Enum

class ActionAuthority(str, Enum):
    OBSERVE = "observe"
    SUGGEST = "suggest"
    AUTONOMOUS = "autonomous"
    APPROVAL_REQUIRED = "approval_required"

@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    plugin_id: str
    capability: str
    authority: ActionAuthority
    reversible: bool
    external_effect: bool
    affects_commitment: bool
    risk: str
    payload_digest: str

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    approval_required: bool
    reason_code: str
    explanation: str
~~~

策略优先级从高到低：

1. 禁止规则。
2. 能力必须来自已注册且 ready 的插件 Manifest。
3. 插件 manifest 权限。
4. Agent 权限；权限拒绝不能通过审批解除。
5. 外部承诺、支付、消息、删除、不可逆操作强制审批。
6. 可恢复的内部动作才允许 Autonomous。
7. 不能判断时默认 Suggest，不得默认执行。

安全修订：审批只会收紧已具备执行资格的动作，不会补发插件或 Agent 权限。
审批后的最终提交必须重新核验 action_id、payload_digest、provider 和权限集合。

### 9.2 审计字段

每个策略判断和插件调用至少记录：

- actor
- operation
- resource
- decision
- reason_code
- correlation_id
- timestamp
- result
- plugin_id
- capability
- payload_digest

审计日志禁止记录知识正文、凭证、财务截图内容和健康原始数据。

### 9.3 关键测试

~~~text
test_read_only_action_is_allowed_without_approval
test_reversible_internal_action_can_be_autonomous
test_external_commitment_requires_approval
test_external_message_requires_approval
test_irreversible_delete_requires_approval
test_unknown_action_defaults_to_suggest
test_agent_autonomy_level_is_not_raised_for_approval_flow
test_audit_redacts_sensitive_payload
~~~

**WP2 完成门槛：**

- 所有新执行路径能返回 PolicyDecision。
- 现有 Agent autonomy_level 均不超过 2。
- network_mode 仍为 OFF。
- 无正文或凭证进入审计。

## 10. WP3：编排层骨架

**目标：** 把自然语言意图转换为逻辑链和能力执行计划，但暂不启用自动外部写入。

**依赖：** WP2。

**文件：**

- 新建：orchestration/__init__.py
- 新建：orchestration/contracts.py
- 新建：orchestration/intent_router.py
- 新建：orchestration/flow_registry.py
- 新建：orchestration/planner.py
- 新建：orchestration/executor.py
- 新建：orchestration/errors.py
- 新建：tests/test_orchestration_contracts.py
- 新建：tests/test_intent_router.py
- 新建：tests/test_capability_planner.py
- 新建：tests/test_orchestration_executor.py

### 10.1 编排合同

~~~python
class FlowName(str, Enum):
    CAPTURE = "capture"
    PLAN = "plan"
    TODAY = "today"
    ADJUST = "adjust"
    REVIEW = "review"
    EXPLORE = "explore"

@dataclass(frozen=True)
class UserIntent:
    flow: FlowName
    text: str
    confidence: float
    evidence: tuple[str, ...]
    correlation_id: str

@dataclass(frozen=True)
class CapabilityCall:
    step_id: str
    plugin_id: str
    capability: str
    payload: dict[str, Any]
    depends_on: tuple[str, ...] = ()

@dataclass(frozen=True)
class ExecutionPlan:
    flow: FlowName
    intent: UserIntent
    steps: tuple[CapabilityCall, ...]
    assumptions: tuple[str, ...]
    requires_confirmation: bool
~~~

### 10.2 Intent Router

- 先使用可测试的规则和结构化输入。
- 允许注入 LLM 分类后端，但测试不得依赖网络或真实模型。
- 低置信度时返回澄清需求，不猜测高风险意图。
- 一次输入可包含多个对象，但只能有一个主逻辑链；次级动作作为计划步骤。

### 10.3 Capability Planner

- 只从 Plugin Registry 选择能力。
- 不 import 具体领域实现。
- 缺能力时返回缺口说明，不静默降级。
- 计划必须是有向无环图。
- 每个有副作用的步骤都必须经过 ActionPolicy。

### 10.4 Executor

- 只通过 RuntimeKernel 和已注册插件执行。
- dry_run=True 时只返回计划、策略结果和预期变更。
- 步骤失败时停止依赖步骤，独立只读步骤可继续。
- 产生部分结果时必须标记 partial，不得报告 completed。

关键测试：

~~~text
test_router_maps_capture_language_to_capture
test_router_requests_clarification_for_low_confidence_high_risk_input
test_planner_uses_only_registered_capabilities
test_planner_rejects_dependency_cycle
test_executor_dry_run_has_no_side_effects
test_executor_blocks_unapproved_external_write
test_executor_marks_partial_result
~~~

**WP3 完成门槛：**

- 六条逻辑链均能被识别。
- dry-run 可以端到端生成计划。
- 尚未迁移的能力以明确 gap 返回。
- 无任何真实外部写入。

## 11. WP4：第一批核心插件适配

**目标：** 通过适配器把现有 Task、Calendar、Body、Information 能力纳入插件系统，不复制业务逻辑。

**依赖：** WP3。

**文件：**

- 新建：capability_plugins/task/
- 新建：capability_plugins/calendar/
- 新建：capability_plugins/body/
- 新建：capability_plugins/information/
- 新建：tests/plugins/test_task_plugin.py
- 新建：tests/plugins/test_calendar_plugin.py
- 新建：tests/plugins/test_body_plugin.py
- 新建：tests/plugins/test_information_plugin.py
- 修改：capability_plugins/manifests/ 对应 YAML

### 11.1 Task Plugin

提供：

- task.parse
- task.list
- task.create_proposal
- task.update_proposal
- task.prioritize

写入仍通过现有飞书 Processor；插件本身不得裸调 lark-cli。

### 11.2 Calendar Plugin

提供：

- calendar.list_events
- calendar.find_free_slots
- calendar.check_conflict
- calendar.create_proposal
- calendar.move_proposal

固定会议和外部承诺必须标记 affects_commitment=True。

### 11.3 Body Plugin

提供：

- body.current_energy
- body.recovery_context
- body.training_context
- body.adjustment_suggestion

只读 Garmin 三层契约，不更改既有文件名和统计来源。

### 11.4 Information Plugin

包装现有 information_system：

- information.capture
- information.recognize
- information.get
- information.list_inbox
- information.propose_domain

不得复制 InformationObject 或 DomainRecord 数据模型。

### 11.5 行为等价测试

每个适配器至少包含：

- 输入映射测试。
- 输出映射测试。
- 旧实现异常映射测试。
- 权限测试。
- 无直接外部写入测试。
- 与旧入口同样输入得到等价核心字段的契约测试。

**WP4 完成门槛：**

- 四个插件只做适配，不复制核心算法。
- 原有测试全绿。
- 插件关闭后旧入口仍可工作。
- 插件异常不会破坏 Registry。

## 12. WP5：Capture / Today / Adjust 纵向闭环

**目标：** 交付第一条可真实使用的完整用户体验闭环。

**依赖：** WP4。

**文件：**

- 新建：experience_layer/__init__.py
- 新建：experience_layer/contracts.py
- 新建：experience_layer/service.py
- 新建：experience_layer/presenter.py
- 新建：experience_layer/flows/__init__.py
- 新建：experience_layer/flows/capture.py
- 新建：experience_layer/flows/today.py
- 新建：experience_layer/flows/adjust.py
- 新建：tests/experience/test_capture_flow.py
- 新建：tests/experience/test_today_flow.py
- 新建：tests/experience/test_adjust_flow.py
- 新建：tests/e2e/test_capture_today_adjust.py

### 12.1 Capture

流程：

~~~text
输入 → Information Capture → 识别对象与关系 → 提取动作
     → 生成能力计划 → 策略判断 → 执行或请求确认 → 用户摘要
~~~

用户不填写表单。输出只展示：

- 系统理解了什么。
- 已记录什么。
- 准备执行什么。
- 哪些动作需要确认。
- 不确定之处。

### 12.2 Today

聚合最小集合：

- 当日固定日历。
- 到期和高优先任务。
- 当前身体能量。
- 外部承诺。
- 可移动任务。

输出必须区分：

- 硬约束。
- 建议安排。
- 自动调整项。
- 待用户确认项。

### 12.3 Adjust

调整规则：

- 新状态先做影响分析。
- 固定会议、外部承诺、强制截止不得自动取消或移动。
- 可恢复的内部任务可在策略允许时自动重排。
- 每次变化必须说明原因和前后差异。

### 12.4 端到端测试场景

| 测试名 | 固定输入 | 必须断言 |
|---|---|---|
| test_low_energy_replans_movable_tasks_but_preserves_commitments | 14:00 固定会议、一个可移动深度任务、身体能量 low | 会议开始时间不变；深度任务被降级或移动；结果含 reason_code 和 before/after diff |
| test_capture_creates_proposal_for_external_commitment | “我答应周五前把资料发给李明” | 识别 Person、Commitment、Task；生成 approval_required 动作；没有 send_message 调用 |

**WP5 完成门槛：**

- 一句自然语言能完成 Capture，不要求用户选模块。
- Today 在离线 fixture 下稳定生成计划。
- Adjust 不破坏硬约束。
- 所有外部副作用可预览、可阻止、可审计。
- 前端不暴露插件内部名称，除非进入诊断模式。

## 13. WP6：Plan / Review / Explore

**目标：** 完成六条逻辑链，并接入 Goal、Project、Learning、Knowledge。

**依赖：** WP5。

**文件：**

- 新建：capability_plugins/goal/
- 新建：capability_plugins/project/
- 新建：capability_plugins/learning/
- 新建：capability_plugins/knowledge/
- 新建：experience_layer/flows/plan.py
- 新建：experience_layer/flows/review.py
- 新建：experience_layer/flows/explore.py
- 新建：tests/plugins/test_goal_plugin.py
- 新建：tests/plugins/test_project_plugin.py
- 新建：tests/plugins/test_learning_plugin.py
- 新建：tests/plugins/test_knowledge_plugin.py
- 新建：tests/experience/test_plan_flow.py
- 新建：tests/experience/test_review_flow.py
- 新建：tests/experience/test_explore_flow.py

### 13.1 Plan

必须形成：

~~~text
Goal → Current State → Gap → Project → Milestone → Task → Calendar Proposal
~~~

Goal、Project 和 Task 是不同对象，不允许把目标直接退化为待办列表。

### 13.2 Review

统一结构：

~~~text
Behavior → Result → Trend → Problem → Cause Hypothesis
→ Recommendation → Next Cycle
~~~

Review 只能把原因表达为假设，除非有足够证据。长期规则必须进入 WP8 的候选流程。

### 13.3 Explore

- 通过 Gateway 和受控上下文读取个人数据与知识。
- 结论附证据、时间范围和置信度。
- 数据不足时明确说不足。
- Explore 默认只读；产生行动必须回到 Capture 或 Plan。

**WP6 完成门槛：**

- 六条逻辑链均有统一 Request/Response。
- Plan 产物可被 Today 消费。
- Review 产物可被下一周期 Plan 消费。
- Explore 不绕过 Gateway。

## 14. WP7：个人领域插件

**目标：** 按低摩擦和渐进激活原则加入 Social、Finance、Life Admin、Creation、Interest、Experience。

**依赖：** WP6。

每个领域单独分支、单独提交、单独验收。顺序建议：

~~~text
Social → Life Admin → Finance → Creation → Interest → Experience
~~~

公共规则：

- 先写 Schema 和 manifest，再写实现。
- 没有真实使用场景的字段不添加。
- 插件默认 dormant，首次真实需求才 active。
- 不为了“完整”创建空表和空记录。

### 14.1 Social

**文件：**

- 新建：capability_plugins/social/
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/SocialPerson.json
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/SocialInteraction.json
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/SocialCommitment.json
- 新建：tests/plugins/test_social_plugin.py

核心对象仅限 Person、Interaction、Commitment。

默认可见字段仅限：

- 姓名
- 关系
- 上次联系
- 下次关注
- 未完成承诺

验收场景：“昨天和小王吃饭，他准备年底换工作；我答应周末发简历模板。”系统自动识别人、互动、上下文和承诺，不要求填联系人表。

Social 的事件和承诺执行态进入飞书；InformationObject 保留来源与识别投影。Person 只保存最小关系索引，不复制完整通讯录。

### 14.2 Life Administration

**文件：**

- 新建：capability_plugins/life_admin/
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/LifeAdminItem.json
- 新建：tests/plugins/test_life_admin_plugin.py

仅包含：

- 证件与身份
- 住房与生活设施
- 个人资产维护
- 服务与合同
- 行政手续

验收场景：“护照明年 3 月到期”首次出现时激活对应子领域并提出提醒计划；未涉及汽车时不得生成汽车模块。

Life Admin 只把已激活对象的状态和提醒写入飞书；Dormant 子领域不创建记录。

### 14.3 Finance

**文件：**

- 新建：capability_plugins/finance/
- 新建：capability_plugins/finance/ports.py
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/FinanceMonthlySnapshot.json
- 新建：tests/plugins/test_finance_plugin.py
- 新建：tests/fixtures/finance/

只支持月度快照：

- 总收入
- 总支出
- 结余
- 储蓄率
- 消费结构
- 大额支出
- 环比
- 异常
- AI 分析
- 下月关注

视觉/OCR 必须通过可注入端口，自动测试使用固定 fixture，不依赖真实云模型。禁止新增逐笔流水模型。

### 14.4 Creation

**文件：**

- 新建：capability_plugins/creation/
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/CreationItem.json
- 新建：tests/plugins/test_creation_plugin.py

生命周期固定为：

~~~text
Idea → Draft → Production → Publish → Feedback → Archive
~~~

执行态在飞书；长正文和作品认知态使用 Knowledge 指针，不双写正文。

### 14.5 Interest

**文件：**

- 新建：capability_plugins/interest/
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/InterestTopic.json
- 新建：tests/plugins/test_interest_plugin.py

Interest 不强制任务化，不设置 KPI，不要求连续记录。只提供：

- 记录兴趣主题。
- 追加轻量探索事件。
- 在 Explore 中回顾。
- 用户主动要求时转为 Project。

### 14.6 Experience

**文件：**

- 新建：capability_plugins/experience/
- 新建：04_数据中心（Data）/数据模型（Schema）/04_个人领域/ExperienceEvent.json
- 新建：tests/plugins/test_experience_plugin.py

生命周期固定为：

~~~text
Wishlist → Planned → Booked → Experienced → Reflection
~~~

长期形成 Personal Experience Timeline。Reflection 只有在用户确认后才能升格为长期经验或原则。

**WP7 完成门槛：**

- 每个插件可单独关闭。
- dormant 插件不产生提醒和维护负担。
- Social 一次自然语言输入完成记录。
- Finance 没有逐笔流水。
- Interest 没有 KPI。
- 所有外部写入均遵守 ActionPolicy。

## 15. WP8：Personal Intelligence 闭环

**目标：** 从多次行为与结果中形成可解释、可验证、可撤销的个人规则候选。

**依赖：** WP5、WP6，且至少有稳定 Review 数据。

**文件：**

- 修改：personal_intelligence/models.py
- 修改：personal_intelligence/engine.py
- 修改：personal_intelligence/self_model.py
- 修改：personal_intelligence/decision_history.py
- 新建：personal_intelligence/rule_candidates.py
- 新建：personal_intelligence/evidence.py
- 新建：tests/test_personal_rule_candidates.py
- 修改：tests/test_phase5_personal_intelligence.py

规则生命周期：

~~~text
Observation → Hypothesis → Evidence → Validation
→ Personal Rule Candidate → Human Approval → Active Rule
~~~

硬规则：

- 单次行为不能生成永久规则。
- 每条候选包含支持证据、反例、时间范围、置信度和适用范围。
- 候选规则不能自动修改 Identity、Value、Principle 或系统配置。
- 用户可以拒绝、撤销或降级规则。
- Decision Engine 使用规则时必须记录 rule_id。

关键测试：

~~~text
test_single_observation_does_not_create_rule
test_repeated_evidence_creates_candidate_not_active_rule
test_counterexample_lowers_confidence
test_rule_activation_requires_human_approval
test_decision_records_rule_id
test_revoked_rule_is_not_used
~~~

**WP8 完成门槛：**

- 不训练模型。
- 不自动改写核心自我模型。
- 每个规则都能追溯到证据。
- 规则对 Today/Adjust 的影响可解释和撤销。

## 16. WP9：可观测性、恢复与迁移收口

**目标：** 让系统长期可运行、失败可发现、变更可回滚，并逐步退出旧路径。

**依赖：** WP6；最终验收依赖 WP7、WP8。

**文件：**

- 修改：scripts/health_check.py
- 修改：scripts/verify.py
- 新建：scripts/plugin_inventory.py
- 新建：scripts/flow_smoke_test.py
- 新建：07_系统文档（Docs）/PLUGIN_INVENTORY.md
- 新建：07_系统文档（Docs）/MIGRATION_MATRIX.md
- 新建：07_系统文档（Docs）/RUNBOOK.md
- 新建：tests/test_plugin_inventory.py
- 新建：tests/test_flow_smoke.py

必须可观测：

- flow_started / flow_completed / flow_failed
- plan_created
- policy_allowed / policy_blocked / approval_required
- plugin_started / plugin_completed / plugin_failed
- partial_result
- rollback_started / rollback_completed

不得记录：

- 凭证
- 知识正文
- 财务截图正文
- 健康原始数据
- 完整外部消息正文

迁移矩阵至少包含：

| 旧入口 | 新入口 | 等价测试 | 当前状态 | 回滚路径 | 可否删除 |
|---|---|---|---|---|---|
| input_parser shim | Capture | 测试文件 | shadow | 旧入口 | 否 |
| daily_scheduler | Today | 测试文件 | shadow | 旧入口 | 否 |
| body_os handler | Body Plugin | 测试文件 | adapted | 旧入口 | 否 |

旧入口删除必须满足：

1. 两个连续验收周期无回退。
2. 行为等价测试通过。
3. 用户确认。
4. 独立删除计划。

**WP9 完成门槛：**

- 一条命令输出插件状态和能力清单。
- 一条命令离线冒烟六条逻辑链。
- 可模拟插件不可用、权限拒绝、部分失败。
- Runbook 含恢复步骤。
- 本工作包不删除旧路径。

## 17. WP10：总验收与版本冻结

**目标：** 证明系统已经完成本轮目标，而不是仅证明代码能运行。

**依赖：** WP0–WP9 全部验收通过。

### 17.1 自动化门禁

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify.py
.\.venv\Scripts\python.exe scripts\plugin_inventory.py
.\.venv\Scripts\python.exe scripts\flow_smoke_test.py
git diff --check
~~~

要求：

- 零失败。
- 不得减少既有测试数量；若删除测试，必须有 ADR 和等价覆盖证明。
- 所有新包进入 compile/verify 范围。
- network_mode 默认仍 OFF。
- 默认 Agent 自治等级不超过 2。

### 17.2 十个产品验收场景

1. Capture 任务：“周五前交项目报告。”
2. Capture 社交承诺：“我答应周末给李明发资料。”
3. Plan：“两个月完成专业课第一轮。”
4. Today：同时存在固定会议、到期任务和低身体能量。
5. Adjust：“昨晚只睡 5 小时。”
6. Review：上传一份月度财务截图 fixture。
7. Explore：“最近为什么总拖延？”
8. Life Admin：首次提到护照到期。
9. Interest：记录兴趣但不创建 KPI。
10. 故障：Calendar Plugin 不可用时，系统返回部分结果和恢复建议。

### 17.3 用户成本指标

- Capture：用户输入一次，除高风险歧义外不追问字段。
- Social：记录一次互动不超过一次输入。
- Finance：每月一次上传，系统完成结构化与分析。
- Dormant 领域：没有真实事件时零维护。
- Today：首屏只显示硬约束、建议、变更和待确认项。
- 所有建议都能回答“为什么”。

### 17.4 安全验收

- 外部消息不得未经批准发送。
- 固定会议不得被自动取消。
- 支付、转账、投资不得自动执行。
- 不可逆删除不得自动执行。
- Agent 不得直接访问 Vault。
- 审计不得泄露正文或凭证。
- 插件关闭时不得留下隐式后台动作。

### 17.5 恢复验收

- 任一插件禁用后核心 Runtime 仍启动。
- 单步骤失败不会伪装为全部成功。
- 计划中的自动调整有 before/after diff。
- 可通过 Git 提交回滚代码。
- 外部写入若无法物理回滚，必须提供补偿动作和人工处理清单。

### 17.6 版本冻结

全部通过后：

- 更新 CHANGELOG。
- 更新 README 和 SYSTEM_BLUEPRINT。
- 生成总验收报告。
- 创建 annotated tag，建议名称：yushu-adaptive-os-v1.0。
- Tag 前再次运行全部门禁。

## 18. 验收评分表

每个工作包满分 100，低于 85 不通过；任何红线项失败直接不通过。

| 维度 | 分值 | 判断 |
|---|---:|---|
| 需求覆盖 | 20 | 工作包所有交付物和场景均覆盖 |
| 架构边界 | 15 | 无绕过 Runtime/Gateway/Processor |
| 权限安全 | 20 | 策略、审批、敏感数据符合要求 |
| 测试质量 | 15 | 失败测试先行，边界和异常覆盖 |
| 用户阻力 | 10 | 未引入额外表单和维护动作 |
| 可解释与审计 | 10 | 原因、证据、变更、correlation_id 完整 |
| 可恢复 | 5 | 有回滚或补偿路径 |
| 文档同步 | 5 | 文档、manifest、迁移矩阵一致 |

红线项：

- 未经批准的外部写入。
- 降低 network 默认安全级别。
- Agent 直接访问 Vault 或外部 API。
- 覆盖或删除用户未提交改动。
- 静默修改事实源。
- 把不完整结果报告为 completed。
- 为追求测试通过而删除有效测试。

## 19. 执行 AI 的标准任务提示词

每次只把一个工作包交给一个执行 AI，使用以下模板：

~~~text
你负责执行《Yushu-OS 下一阶段总执行计划》的 WPXX。

开始前：
1. 阅读总计划、README、SYSTEM_BLUEPRINT、相关 ADR 和本工作包列出的现有文件。
2. 运行并记录基线测试、scripts/verify.py、git status。
3. 不覆盖当前工作区的未提交改动；使用独立分支或 worktree。

执行要求：
- 只做 WPXX，不提前做后续工作包。
- 严格 TDD。
- 不改变 network_mode: OFF。
- 不提高 Agent 自治等级。
- 不绕过 Runtime、Knowledge Gateway 或飞书 Processor。
- 每个提交只表达一个意图。

交付时提供：
- 分支与提交 SHA
- diff stat 和文件清单
- 目标测试、全量测试、verify 结果
- 手工场景证据
- 风险与回滚方式
- 外部写入说明
- 未完成项
~~~

## 20. 验收 AI 的标准提示词

~~~text
你负责验收 Yushu-OS 的 WPXX，不负责替执行者补实现。

先读取：
- 总执行计划中 WPXX 的目标、文件和完成门槛
- 执行者提交 SHA 与验收证据
- 实际 git diff

验收顺序：
1. 检查范围漂移和用户已有改动是否被污染。
2. 检查架构边界与安全红线。
3. 重跑目标测试、全量测试、scripts/verify.py。
4. 独立执行本工作包的手工场景。
5. 检查文档、manifest、代码和测试是否一致。
6. 按 100 分制评分。

输出只能是：
- PASS：分数、证据、允许进入下一工作包。
- FAIL：阻断项、复现方式、必须修复的最小清单。
- CONDITIONAL PASS：仅允许不影响后续的文档性小问题，并给出截止工作包。
~~~

## 21. 最终成功定义

本轮不是以“插件数量”或“代码行数”判断成功，而是同时满足：

1. 用户通过六条逻辑链使用系统，不需要理解后台模块。
2. 系统能枚举和解释自己的能力。
3. 每个动作在执行前经过统一权限判断。
4. Capture、Today、Adjust 形成真实闭环。
5. 领域按需激活，不增加无意义维护。
6. Finance 保持月度快照，Social 保持事件驱动。
7. Personal Intelligence 只从多次证据形成候选规则。
8. 所有关键路径可测试、可观察、可审计、可恢复。
9. 旧系统在迁移期间持续可用。
10. 用户的管理成本和认知模糊实际下降。
