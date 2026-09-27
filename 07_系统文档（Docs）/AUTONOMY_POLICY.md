# Yushu-OS 动作权限与自治策略

> 状态：Accepted
> 适用范围：所有编排计划、插件调用和 Agent 执行

## 1. 两个不同概念

动作权限和 Agent 自治等级不是同一件事。

- 动作权限：某一个具体动作现在能否执行。
- Agent 自治等级：一个 Agent 的长期治理上限。

Approval Required 表示动作必须进入审批流程，不表示把 Agent 自治等级提升到 Level 3。现有 Agent 自治上限保持 Level 2。

## 2. 四类动作权限

| 权限 | 含义 | 示例 |
|---|---|---|
| Observe | 只读观察与分析 | 读取今日任务、分析睡眠趋势 |
| Suggest | 提出建议，不修改状态 | 建议降低训练负荷 |
| Autonomous | 可恢复、内部、低风险动作 | 调整内部任务排序 |
| Approval Required | 必须先得到用户批准 | 发送消息、移动固定会议、删除数据 |

## 3. Autonomous 的全部条件

只有同时满足以下条件才可自动执行：

- 只影响用户内部事务。
- 不改变与他人的承诺。
- 不涉及支付、转账或投资。
- 不发送外部消息。
- 动作可撤销或有确定补偿方案。
- 风险为 low。
- 插件和 Agent 均拥有所需权限。
- 审计可完整记录原因和变化。

任一条件不满足时降级为 Suggest 或 Approval Required。

## 4. 强制审批动作

- 创建、取消或移动外部承诺。
- 创建、取消或移动固定会议。
- 发送重要外部消息。
- 支付、转账、投资和购买。
- 删除事实源数据。
- 不可逆迁移。
- 修改 Identity、Value、Principle 或正式 Personal Rule。
- 提升权限、改变事实源或降低安全默认值。

## 5. 默认拒绝

无法确定风险、可逆性、外部影响或权限时，不执行，并返回 Suggest 及缺失信息。禁止把“不知道”解释为“允许”。

## 6. 决策优先级

~~~text
禁止规则
  → 能力必须来自已注册且 ready 的 Plugin Manifest
  → Plugin Manifest 权限
  → Agent 权限
  → 强制审批规则
  → 可逆性与外部影响
  → 最小权限结果
~~~

上层规则不能被下层覆盖。
权限拒绝不能通过审批解除。审批只会进一步收紧一个原本具备执行资格的动作，
不会补发 Plugin 或 Agent 权限；审批后的最终提交仍须重新核验同一 action_id、
payload_digest、provider 和权限集合。

## 7. 审批语义

- 审批只对具体 action_id 和 payload_digest 生效。
- Payload 变化后原审批失效。
- 审批必须记录 reviewer、timestamp、reason 和 correlation_id。
- 拒绝、过期和已使用的审批不能重复消费。
- 一次性敏感访问继续沿用现有 Access Request 语义。

## 8. 可解释与恢复

每个执行结果必须包含允许或阻止的原因、使用的约束、修改前后差异、可撤销性和补偿步骤。

## 9. 永久不变量

- network_mode 默认 OFF。
- Agent autonomy_level 不超过 Level 2。
- Agent 不直接访问 Vault 或外部 API。
- 未经批准不执行高风险外部副作用。
- 审计不保存敏感正文。
