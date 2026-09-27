# WP5 Capture / Today / Adjust 纵向闭环验收报告

> 日期：2026-09-27
> 结论：PASS
> 分支：codex/yushu-wp5-experience
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP5 交付第一条可实际使用的体验层闭环：用户以自然语言进入 Capture、Today 或 Adjust，体验层负责路由、能力规划、权限执行和面向用户的分类展示。默认界面不暴露插件名或 capability；外部承诺、固定会议和强制截止不会被静默执行、移动或取消。

本轮继续保留 WP0 前已有的未提交变化，没有重置、清理或恢复用户文件。

## 2. 交付物

新增：

- experience_layer/__init__.py
- experience_layer/contracts.py
- experience_layer/service.py
- experience_layer/presenter.py
- experience_layer/flows/__init__.py
- experience_layer/flows/capture.py
- experience_layer/flows/today.py
- experience_layer/flows/adjust.py
- tests/experience/test_contracts.py
- tests/experience/test_service.py
- tests/experience/test_capture_flow.py
- tests/experience/test_today_flow.py
- tests/experience/test_adjust_flow.py
- tests/e2e/test_capture_today_adjust.py

扩展：

- orchestration/flow_registry.py
- orchestration/contracts.py
- orchestration/executor.py
- runtime_core/audit.py
- tests/test_intent_router.py
- tests/test_orchestration_contracts.py

## 3. 已冻结的体验合同

- ExperienceRequest、ExperienceItem、ExperienceResponse 提供三条流程统一边界。
- ExperienceRequest 默认执行安全的内部工作；Executor 本身仍保持 dry-run 默认，外部或承诺类动作仍由 Kernel 策略阻断。
- Request context、Item before/after、Response diagnostics 均建立递归不可变快照。
- CapabilityCall payload 改为 tuple-backed Mapping/Sequence，不可通过普通赋值、dict/list 基类方法、内部槽位内容或槽位重赋绕过。
- Runtime 审计对不可变 Mapping/Sequence 做规范化摘要，不存原始正文。
- ExperiencePresenter 默认只输出面向用户的理解、记录、硬约束、建议、自动调整、待确认与不确定项；diagnostic=True 才输出内部诊断。

## 4. Capture 闭环

输入“我答应周五前把资料发给李明”时：

- IntentRouter 无需用户选择模块即可路由到 Capture。
- 识别 Person=李明、Commitment=周五前发送资料、Task=把资料发给李明。
- 原文通过 information.capture 写入本地 InformationStore。
- task.create_proposal 带 affects_commitment=True，并由 Kernel 返回 approval_required_external_commitment。
- 承诺步骤不调用 Task 插件、不发送消息；用户获得待确认项。
- 审计仅记录 capability、reason、pending_approval 和 payload digest，不记录原文。
- 普通记录只调用 information.capture，不强制生成任务。

## 5. Today 闭环

Today 只读取并聚合：

- calendar.list_events；
- task.list；
- body.current_energy。

输出规则：

- 未显式标记 movable=True 的旧日历事件默认是硬约束。
- 固定会议、外部承诺、当天截止和强制截止任务是硬约束。
- 高优先任务、显式可移动日历/任务进入建议安排。
- 低能量下，仅可逆、非承诺、非截止、非固定的内部任务可进入自动调整。
- suggested_start 必须有完整 start/end，保持原时长，并校验截止时间、硬日历及其他任务冲突；不安全时转待确认。
- 截止日期兼容 YYYY-MM-DD 与旧系统 YYYY/MM/DD。
- 单个来源失败时保留其他有效来源并返回 partial；全部不可用时 blocked。

## 6. Adjust 闭环

- 能量缺失或过期时不调整，返回 energy_signal_unavailable。
- 正常能量返回 no_adjustment_needed。
- 低能量时，固定会议、外部承诺原样进入 hard_constraints。
- 强制截止、外部日历变更和无安全方案的任务进入 confirmations。
- 可移动深度任务优先选择无冲突候选时段；无时段且允许降级时改为 light。
- 可逆内部变化进入 automatic_adjustments，均包含稳定 reason_code 与 before/after。
- Adjust 是纯逻辑，不调用插件、Executor、数据库或外部日历，也不宣称已持久化。

## 7. TDD 证据

主要 RED：

- experience_layer 不存在时，公共合同与 Service/Presenter 测试 10 项先失败。
- CaptureFlow 不存在时 5 项失败；实现后自然语言抽取、规划 gap、dry-run 预览和展示隔离转绿。
- “我答应……”最初被高风险路由为澄清；增加明确 Capture cue 后转绿。
- Capture E2E 最初把承诺任务执行为 completed；Executor 从通用 payload 读取 affects_commitment 后转为审批阻断。
- Adjust 初版将内部可逆变化列为 suggestion；分类测试先失败，改为 automatic_adjustments 后转绿。
- Experience 层默认 dry_run=True 导致 Capture 只预览；默认入口测试先失败，改为安全内部执行后转绿。
- CapabilityCall 的 dict/list 子类可被基类方法绕过；绕过测试先失败，改为真正不可变 Mapping/Sequence 后转绿。
- 不可变对象的私有槽位仍可重赋；槽位测试先失败，改为无实例状态 tuple 子类后转绿。
- Today 初版把未标 movable 的旧日历当可移动、会调整承诺/截止任务、盲信 suggested_start；4 项安全测试先失败，加入默认硬约束与冲突/时长校验后转绿。
- Today 不识别 YYYY/MM/DD 截止；斜杠日期测试先失败，兼容归一化后转绿。

## 8. 最终验证

- WP5 Experience + E2E + Orchestration 关联回归：110 passed。
- scripts/verify.py：768 passed、47 subtests passed，退出码 0。
- Today + E2E 专项：18 passed。
- WP5 scoped git diff --check：通过。
- 三个端到端场景均使用离线 fixture；无测试网络访问。

## 9. 独立审查

- Capture/公共合同架构安全复审：先后发现默认只预览、dict 基类绕过和槽位重赋；逐项修复后 PASS，聚焦 63 passed，全量 768 + 47。
- Today 业务与测试复审：先后发现旧日历默认分类、承诺/截止自动调整、冲突/时长、斜杠日期问题；逐项修复后 PASS，Today + E2E 18 passed。
- Adjust/E2E/差异安全复审：PASS；硬约束、自动调整、审计、不可变 payload 和范围 diff 均通过，全量 768 + 47。

## 10. 已知非阻断项

- ExperienceResponse.diagnostics 有内部 plugin/capability 标识；正式 UI 必须经 ExperiencePresenter 输出，不能直接序列化原始 Response。
- Today 的自动调整是本地计划草案，不代表外部日历或任务源已写入；外部变更仍需后续受权执行链。
- Capture 当前使用确定性规则识别示例承诺；更复杂自然语言仍可能进入不确定项或需要后续分类能力。

## 11. 外部副作用与回滚

- 外部写入：无。
- 飞书写入：无。
- 日历写入：无。
- 消息发送：无。
- Information 写入：仅用户 Capture 的本地内部记录；测试使用 pytest 临时 SQLite。

回滚仅移除 experience_layer、WP5 测试、本报告，以及本轮对 Router、不可变 payload、Executor commitment 标记和审计规范化的扩展；不得覆盖其他工作包或 WP0 前已有修改。
