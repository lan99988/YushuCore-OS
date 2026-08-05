# Phase 5 Cognitive Proposal Workflow

## 标准流程

```text
Observation
↓
Pattern Discovery
↓
Cognitive Analysis
↓
Proposal
↓
Human Review
↓
Approved Update
```

## Proposal 最小结构

```yaml
proposal_id:
agent_id:
type: cognitive
observation:
pattern:
question:
reason:
evidence: []
confidence:
risk:
target_layer:
status: pending_human_review
correlation_id:
created_at:
```

## 约束

- Pattern 是待验证发现，不是对 Human 的事实宣告。
- `target_layer` 为 Identity、Value、Principle 时只能提出问题或建议，不得自动更新。
- Proposal 不执行外部任务，不改变学习、训练、项目或人生计划。
- 审批、拒绝、过期和撤销都必须可审计。
