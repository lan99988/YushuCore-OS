# Phase 5 Personal Intelligence Engine Technical Design

日期：2026-08-05  
状态：Started / Design Gate  
前置：`phase4-integration-accepted-v1.0`

## 目标

在不突破 Gateway First、Human Approval、Local First 和 Markdown First 的前提下，建立个人认知模型的只读分析与提案基础设施。

## 首批范围

1. `Self Model`：通过 Knowledge Gateway 读取并汇总 Values、Goals、Preferences、Thinking、Decision、Behavior。
2. `Decision History`：记录决策、证据、结果和反馈，不自动修改核心原则。
3. `Cognitive Proposal`：输出 Reason、Evidence、Confidence、Risk 和 Approval 状态。
4. `Personal Model` 接口：只定义模型路由和版本化契约，不训练或替换基础模型。

## 强制边界

- Agent 不直接读取 `11_Self_Model`，必须经过临时授权和敏感度检查。
- Agent 不得自动写入 Self Model、Personal Memory 或核心原则。
- 高风险认知提案必须 Human Approval。
- 云模型不得接收 Level 3 / Level 4 数据，除非有显式授权和审计记录。
- 所有模型、Prompt、Policy 变更必须可追踪、可回滚。

## 开发顺序

```text
Design
↓
契约测试
↓
只读 Self Model Gateway 查询
↓
Decision History 记录
↓
Cognitive Proposal
↓
Evaluation
↓
Human Acceptance
```

本文件是 Phase 5 的设计起点；在设计评审通过前，不实现自动决策、自动写入或自治执行。
