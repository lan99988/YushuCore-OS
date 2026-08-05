# Phase 5 Personal Memory Governance Model

## Memory 分类

### 可演化 Memory

- 写作习惯
- 工作方式
- 学习方法
- 训练策略偏好
- 经 Human 确认的行为模式

流程：`Experience → Reflection → Proposal → Human Approval → Personal Memory`。

### 核心 Memory（Human Only）

- 人生原则
- 价值排序
- 身份认知
- 长期方向和不可替代的核心判断

核心 Memory 不允许 Agent 自动写入、重写、删除或降级敏感度。

## 写入规则

- Agent 只能追加 Experience 或生成 Proposal。
- Memory Manager 必须拒绝 Agent 对 Personal Memory 的直接写入。
- 批准写入必须包含 reviewer、reason、evidence、before/after digest 和 correlation id。
- 任何失败均保持原值，支持 Git/备份恢复。
