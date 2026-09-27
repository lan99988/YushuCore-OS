# WP2 自治策略与统一审计验收报告

> 日期：2026-09-26
> 结论：PASS
> 分支：codex/yushu-wp2-action-policy
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP2 为所有新增 PlannedAction 建立统一的最小权限判断、审批闸门与仅元数据审计，不启用任何真实外部写入。旧 `ToolManager.call` 仍属遗留路径，其接入统一执行边界安排在 WP3/WP4；本报告不把它误报为已经迁移。

本轮继续保留 WP0 前已存在的未提交变化，没有重置、清理或恢复用户文件。

## 2. 交付物

新增：

- runtime_core/action_policy.py
- runtime_core/audit.py
- tests/test_action_policy.py
- tests/test_audit.py

修改：

- runtime_core/models.py：新增 ActionAuthority、PlannedAction、PolicyDecision。
- runtime_core/kernel.py：新增以 ready Manifest 为可信来源的 authorize_action 执行边界。
- runtime_core/events.py、runtime_core/logger.py：事件历史与持久化日志统一使用安全快照。
- runtime_core/__init__.py：导出 WP2 公共 API。
- config/permission.yaml：明确禁止项和必须人工审批项。
- AUTONOMY_POLICY.md、总执行计划与架构合同测试：冻结“权限拒绝不能由审批解除”的优先级。
- tests/test_runtime_core.py、tests/test_architecture_contracts.py：增加内核、审计和文档合同覆盖。

## 3. 已冻结的行为

- 决策顺序为：绝对禁止 → ready Manifest → 插件权限 → Agent 权限 → 自治上限 → 已知能力 → 强制审批 → 低风险内部自治。
- 审批只会收窄执行权，不会授予缺失权限。
- Agent 自治等级超过系统上限 2 时降级为 Suggest，不自动提权。
- 外部承诺、支付、外部消息、不可逆删除、外部副作用和高风险动作必须审批。
- Kernel 不接受调用方自报的插件权限、风险或副作用；这些值从 Registry 中的 ready Manifest 重建。
- 审计 operation、resource、plugin_id、capability 均来自受控边界，调用方 sentinel 不会写入审计。
- 审计只允许固定元数据字段和 SHA-256 payload digest，拒绝带额外正文属性的 AuditRecord 子类。
- permission.yaml 必须保持 default deny、三个直接访问开关为 false，并要求禁止列表和人工审批列表存在且非空。
- EventBus 的处理器继续收到原始业务事件；history 与 RuntimeLogger 只保存脱敏快照。
- task、payload、content、message、body、text、prompt、凭证、财务截图和健康原始数据等正文键被摘要化；digest/hash 元数据保持可观测。

## 4. TDD 证据

主要 RED：

- WP2 API 尚不存在时，策略与审计测试无法导入。
- 外部动作、不可逆动作、未知动作、权限缺失和自治上限用例先失败。
- Kernel 最初信任调用方 plugin_permissions、operation 和 resource；注入回归测试先失败。
- AuditLogger 最初允许 dataclass 子类增加 payload；精确类型测试先失败。
- 审批最初可能掩盖权限拒绝；安全顺序测试先失败。
- `body_text`、`message_text`、`prompt`、`user_prompt`、`prompt_text` 五个正文键最初可进入 history；5 个回归用例先失败。
- permission.yaml 缺失或使用空的 prohibited_actions / human_approval_required_for 最初会被接受；4 个 fail-closed 用例先失败。

对应 GREEN：

- 完成策略模型、Manifest 信任边界、统一审计和 Kernel 授权后，策略与内核测试通过。
- 使用精确 AuditRecord 类型与字段白名单后，审计注入被拒绝。
- 重排策略优先级并同步合同文档后，权限拒绝不能被审批覆盖。
- 扩展正文键分类后，五种复合正文键均被摘要化。
- 配置加载改为要求两份安全列表存在且非空后，四个 fail-closed 用例通过。

## 5. 最终验证

- WP2 专项联合测试：83 passed（在最终两项加固前）；最终策略专项为 28 passed，审计专项为 12 passed。
- 独立测试审查使用的最终联合测试：115 passed。
- scripts/verify.py：595 passed、47 subtests passed，退出码 0。
- compileall、配置只读约束与 Agent 边界检查全部通过。
- WP2 scoped git diff --check：通过。
- 全仓 git diff --check 的既有异常仍只来自 WP2 前已修改的 handlers/body_os.py；WP2 未编辑该文件。

## 6. 独立审查

- 架构复审：PASS。确认可信 Manifest、权限优先级、审计字段来源与自治上限均符合合同；旧 ToolManager 迁移明确留给 WP3/WP4。
- 测试充分性复审：PASS，最终联合测试 115 passed；缺失/空安全规则列表已有回归覆盖。
- 差异与安全复审：PASS。正文复合键绕过修复后，审计白名单、ready provider 与 handler 原事件语义均未回退。

## 7. 已知非阻断项

- 脱敏仍依赖字段名分类；未来新增正文键时必须同步更新敏感键合同和回归测试。
- correlation_id 当前由调用方提供但受字符集与长度约束；若后续允许直接接收不可信输入，可在编排层改为内部生成 UUID。
- 当前对 Manifest 中任意 writes 声明都保守视为外部副作用；WP4 可在不放宽安全边界的前提下补充更细的能力级 effect 元数据。
- 旧 ToolManager 尚未统一迁移，WP3 Executor 与 WP4 适配器必须只走 Kernel authorize_action 边界。

## 8. 外部副作用与回滚

- 外部写入：无。
- 飞书调用：无。
- Knowledge 写入：无。
- 网络访问：无。

回滚仅需移除 WP2 新增文件与本报告，并撤销 runtime_core、permission.yaml、AUTONOMY_POLICY、总计划和相关测试中的 WP2 增量；不得覆盖这些文件在 WP2 前已有的用户修改。
