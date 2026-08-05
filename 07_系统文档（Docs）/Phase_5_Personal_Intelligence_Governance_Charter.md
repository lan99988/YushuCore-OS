# Personal Intelligence Governance Charter

## 1. Personal Intelligence 定义

Personal Intelligence 是由 Runtime 管理的认知辅助能力集合。AI 可以观察、分析、解释、反思和提出建议；Human Owner 保留价值判断、身份认知、原则和最终行动控制权。

## 2. Human Control Boundary

- 核心认知变更必须由 Human Owner 明确批准。
- Proposal 不等于事实，不等于决定，不等于执行授权。
- 拒绝、过期和撤销必须留下审计记录。
- 所有变更必须可追踪、可回滚。

## 3. Memory 权限

```text
Experience → Reflection → Proposal → Human Approval → Personal Memory
```

Agent 不得跳过 Proposal 和 Approval 直接写入 Personal Memory。Identity、Value、Principle 属于 Human Only。

## 4. 自治限制

Phase 5 当前最大自治等级为 Level 2：主动发现问题、分析趋势、提交建议。Level 3 和 Level 4 禁止启用。

## 5. 审计要求

每次读取、分析、提案、审批、拒绝和回滚必须包含 `agent_id`、`correlation_id`、数据敏感度、reason、evidence、confidence 和时间戳。
