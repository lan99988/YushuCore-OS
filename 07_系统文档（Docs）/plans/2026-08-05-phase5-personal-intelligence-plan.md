# Phase 5 Personal Intelligence Engine Implementation Plan

**Goal:** 建立受治理的 Self Model、Decision History 和 Cognitive Proposal 第一代只读基础能力。

**Architecture:** 复用现有 Personal Agent Runtime、Knowledge Gateway、Memory Manager、Model Router 和 Approval Engine；新增模块只能通过公开 Runtime/Gateway 契约访问敏感个人认知数据。

**Tech Stack:** Python、dataclasses、Markdown/YAML、pytest、现有 JSONL Audit/Memory 存储。

## Phase 5.1 Self Model Read Contract

- 冻结 Self Model 节点类型、敏感度和临时授权接口。
- 先写 Boundary Test，验证普通 Agent 默认拒绝 Level 3/4。
- 实现只读 Context Builder，不提供直接文件访问。

## Phase 5.2 Decision History

- 冻结 decision、evidence、outcome、feedback、timestamp、agent、correlation_id 字段。
- 先写 schema 和审计测试，再实现追加式记录。
- 保证历史记录不可被 Agent 原地修改。

## Phase 5.3 Cognitive Proposal

- 冻结 reason、evidence、confidence、risk、status、approval 字段。
- 只输出 Proposal，不执行现实动作。
- 增加 Capability、Boundary、Explainability 和回滚测试。

## Phase 5.4 Personal Model Interface

- 定义版本化 Model/Prompt/Policy 接口。
- 强制本地优先和高敏数据隔离。
- 暂不训练 LoRA、不替换基础模型、不开放 Level 4 自治。
