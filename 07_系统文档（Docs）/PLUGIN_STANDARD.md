# Yushu-OS 能力插件标准

> 版本：1.0
> 状态：Accepted

## 1. 定义

> Skill ≠ Plugin

- Skill 是 AI 的使用说明：何时以及怎样调用能力。
- Plugin 是系统能力：可以被注册、发现、调用、测试、禁用和审计。

一个 Python 文件不自动等于插件。没有 Manifest、调用合同和测试的模块不是正式插件。

## 2. Manifest 必填字段

~~~yaml
plugin_id: task
name: Task Plugin
version: 1.0.0
purpose: 管理明确可执行行动
domain: task
provides: [task.list, task.create_proposal]
reads: [feishu.task]
writes: [feishu.task]
dependencies: []
permissions: [read_task, propose_task_change]
risk_level: medium
activation_mode: always
availability: installed
enabled: true
activation_state: active
input_contract: {}
output_contract: {}
error_policy: {}
audit_policy: {}
capability_priorities: {}
capability_priority_reasons: {}
~~~

加载器必须拒绝缺失字段、未知字段、非法枚举和重复 plugin_id。
`capability_priorities` 与 `capability_priority_reasons` 为可选映射；只有同一
capability 存在多个 provider 时才填写，并且两者的 capability 键必须完全一致。

## 3. 生命周期维度

生命周期采用三个正交维度：

- availability：installed、unavailable、archived。
- enabled：是否允许 Registry 选择。
- activation_state：active 或 dormant。

Installed、Enabled、Active 不得互相替代。

## 4. 插件接口

插件公开 manifest 和 invoke(capability, payload, context)。

插件不得公开底层凭证、文件路径或内部客户端。调用必须携带 correlation_id 和受控 Runtime Context。

## 5. 注册规则

- plugin_id 全局唯一。
- capability 默认只能有一个提供者。
- 多提供者必须声明显式优先级和选择理由。
- 依赖必须存在且可用。
- dormant 插件不能被自动执行，但可返回激活建议。
- unavailable 插件必须返回具体缺失依赖。
- 状态变化必须写入审计事件。

## 6. 权限与副作用

- 只读能力仍需最小权限。
- 写能力优先产生 Proposal，不直接执行。
- 插件不能自行判定高风险动作已获批准。
- 插件不能提高 Agent 自治等级。
- 外部写入必须经 Runtime 和 Action Policy。
- 飞书写入必须沿用现有 Processor 或受控 Integration。

## 7. 错误合同

统一错误类别包括 capability_not_found、plugin_disabled、plugin_dormant、plugin_unavailable、dependency_unavailable、invalid_input、blocked_by_policy、approval_required、external_failure 和 partial_failure。

错误必须包含安全的用户说明、机器可读 reason_code、correlation_id 和可恢复建议。

## 8. 审计合同

至少记录 actor、plugin_id、capability、operation、resource、decision、reason_code、correlation_id、timestamp、result 和 payload_digest。

禁止记录凭证、正文或原始敏感数据。

## 9. 测试要求

每个插件至少验证 Manifest、输入输出映射、权限允许和拒绝、生命周期状态、异常映射、外部写入边界和旧能力适配时的行为等价。

## 10. 激活原则

核心插件可以 always active。个人领域默认 dormant；第一次出现真实需求时提出激活，低风险且仅影响内部结构时可自动激活，涉及外部写入时仍需审批。
