# WP8 Personal Intelligence 闭环验收报告

> 日期：2026-09-27
> 结论：PASS
> 分支：codex/yushu-wp8-personal-intelligence
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP8 将多次行为与结果形成可解释、可验证、可拒绝、可撤销的个人规则候选，并把已批准规则以只读建议接入 Today 与 Adjust。系统不训练模型，不自动改写 Identity、Value、Principle 或系统配置，不让个人规则越过固定会议、外部承诺和强制截止。

## 2. 规则生命周期

实现的闭环为：

```text
Observation → Hypothesis → Evidence → Validation
→ Personal Rule Candidate → Human Approval → Active Rule
→ Degraded / Revoked
```

- 单条支持证据不生成候选；至少两条独立来源的支持证据才能进入 Candidate。
- 同一 source 重复提交幂等，不增加证据权重，也不留下孤儿 Observation。
- 候选保存支持证据、反例、UTC 时间范围、置信度、scope、target 和提出者。
- 反例降低置信度；低于门槛的 Active Rule 自动降级，不再作为 active 使用。
- 激活、拒绝、撤销和人工降级均通过显式状态转移；终止状态不能跳回 Active。
- 审批人必须来自注入的授权白名单，默认没有授权人；提出者不能自审。

## 3. 证据与完整性

- Evidence ledger 为追加式 JSONL，Observation、Hypothesis、Evidence 使用受控 ID。
- observed_at 必须是带时区 ISO 时间，规范化为 UTC；无效、无时区和未来时间在写入前拒绝。
- supports 必须是 bool，NaN、数字和字符串不能借真值判断成为支持证据。
- Evidence 的 source、时间和摘要必须与对应 Observation 完全一致。
- 每次规则验证重新构建 Observation → Hypothesis → Evidence 关系，检查 ID、来源唯一性和引用存在性。
- 损坏 JSON、未知事件类型及结构合法但语义被篡改的 ledger 均 fail-closed。
- Active Rule 还会把候选快照与实时 hypothesis 的 claim、suggested_action、proposed_by、scope、target、证据、反例、时间和置信度逐项比对。

## 4. 人工审批与核心模型隔离

- PersonalRuleTarget 仅允许 Today、Adjust、Decision Guidance。
- Identity、Value、Principle、system_config 不能成为个人规则 target。
- Self Model 的原有读取与提案政策保持不变；WP8 不调用版本写入接口。
- 审计日志只记录 rule_id、hypothesis_id、reviewer、动作和时间，不复制原始个人证据正文。

## 5. Decision History

- DecisionRecord 增加可选 rule_ids、scope、rule_target，旧 JSONL 缺少新字段时按空值读取。
- scope 匹配不再自动等同“实际使用”；只有决策点显式提供 applied_rule_ids 才记录。
- History 会向绑定的候选存储实时校验每个 ID 的 active 状态、scope、target 和证据完整性。
- 未知、重复、撤销、降级、scope 错配或 target 错配的规则 ID 均被拒绝。
- 历史记录保持追加式；撤销规则不会改写旧决策，但新决策无法再使用它。

## 6. Today / Adjust 接线

- TodayFlow 与 AdjustFlow 增加可选只读 rule_provider；未注入时与旧行为完全兼容。
- 两条 Flow 固定使用受控 planning scope，不信任 request.context.rule_scope 扩权。
- Today 只读取 target=TODAY，Adjust 只读取 target=ADJUST；每次运行实时查询，不缓存规则快照。
- 规则只生成 suggestion，不进入 hard_constraints、automatic_adjustments 或外部写入。
- suggestion 显示 rule_id、支持证据引用和置信度，不复制证据正文。
- 已知硬约束、确认项或既有自动调整存在时抑制规则建议，确保原有安全结果不变。
- 同一 Flow 实例在规则撤销后再次运行，不再返回该规则。

## 7. TDD 与独立审查

- 初始规则候选测试因缺少 Evidence/Rule 模块产生 9 项 RED；基础闭环转绿后为 26 passed。
- 对抗审查发现证据伪造、时间未校验、非 bool supports、target 未匹配、规则 ID 过度归因和损坏 ledger fail-open；新增测试首轮 15 failed、4 passed，逐项修复。
- 架构复核发现合法 JSON 的 hypothesis 文本、动作和提出者篡改仍可保留 Active Rule；新增 3 项 RED，补候选快照逐字段比对后转绿。
- Today/Adjust 接线先以构造器、固定 scope、撤销和硬约束测试形成 RED，再最小接入只读建议。
- 三轮独立复核最终均为 PASS。

## 8. 最终验证

- WP8、Phase 5、Experience 合约、Today/Adjust 与 E2E 聚焦回归：85 passed。
- scripts/verify.py：921 passed、47 subtests passed，退出码 0。
- WP8 受影响路径 git diff --check：通过。
- Public API 可从 personal_intelligence 包根导入 EvidenceStore、RuleEvidence、PersonalRuleCandidate、PersonalRuleCandidateStore、PersonalRuleStatus、PersonalRuleTarget。

## 9. 设计性运行前提

- source_id 的外部真实性仍需由上层可信来源或 Gateway 提供；本轮保证 ledger 内部关联和语义一致，但不提供签名或哈希链。
- authorized_reviewers 必须由可信配置注入，不能来自请求正文。
- Today/Adjust 返回的是规则建议预览；后续真正选择或执行建议时，调用方必须把该 suggestion 的 rule_id 显式传给 Decision History，并再次实时校验。
- 当前规则 scope 固定为 planning；扩大 scope 必须使用受控结构化映射，不接受自由文本扩权。

## 10. 回滚

回滚仅移除 evidence.py、rule_candidates.py、规则模型与 Engine/Decision History 扩展、ExperienceItem 的可选规则字段、Today/Adjust 的可选 rule_provider 接线、对应测试和本报告；不得删除 WP5–WP7 的 Flow、插件或既有个人智能能力，也不得覆盖 WP0 前已有修改。
