# Phase 5 Decision History Model

## 第一阶段定位

Decision History 第一阶段只记录，不自动优化决策，不自动生成行为规则，也不反向修改 Self Model。

## 数据结构

```yaml
decision_id:
decision:
context:
options: []
chosen_action:
reason:
evidence: []
outcome:
reflection:
agent_id:
reviewer:
correlation_id:
created_at:
```

## 生命周期

```text
Draft → Recorded → Outcome Pending → Reflected
```

记录采用追加式写入；修改通过新记录表达，不覆盖原始决策。未来可基于已批准记录研究 Decision Pattern，但不属于当前实现授权范围。
