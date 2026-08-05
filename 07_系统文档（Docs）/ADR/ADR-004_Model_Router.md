# ADR-004 Model Router

Date: 2026-08-05
Status: Accepted
Scope: Runtime Model Routing / Network Governance

## 决策

Runtime 使用 Model Router 进行 Local First 模型路由。默认网络模式为 `OFF`，默认使用本地模型。只有在网络模式允许且任务复杂度较高时，才允许云端模型参与；但 `level_3` / `level_4` 上下文必须强制本地模型。

## 为什么这样设计

Personal Knowledge OS 的知识包含个人经验、原则和未来 Self Model。模型路由必须优先保护高敏数据，而不是优先追求推理能力。

核心规则：

```text
level_3 / level_4 -> local model
OFF -> local model
ASSIST/SYNC + complex/deep/high -> cloud model
```

高敏规则优先级最高。

## 为什么不采用其他方案

### 不默认使用云端模型

默认云端会违反 Local First 和高敏数据隔离原则。

### 不让 Agent 自己选择模型

Agent 自选模型会绕过网络治理与敏感度规则。

### 不只靠用户手动判断

用户手动判断不能覆盖 Agent 自动执行路径。Runtime 必须在执行链路中强制路由。

## 优点

- 默认离线安全。
- 高敏上下文不可上云。
- 复杂任务仍保留云端扩展路径。
- 模型选择有审计事件。
- 与配置文件 `network.yaml` / `model.yaml` 对齐。

## 缺点

- 当前路由规则较简单。
- 未考虑模型健康度、成本、延迟。
- 云端使用只按网络模式和复杂度判断，未来还需更细的任务类型策略。

## 未来如何演化

- 增加模型健康检查。
- 增加成本与延迟策略。
- 增加任务类型路由。
- 增加本地模型 fallback。
- 保持 `level_3` / `level_4` 强制本地规则不可突破。
