# WP9 验收报告

## 结论

**PASS，92/100。允许进入 WP10。**

验收日期：2026-09-27
验收范围：可观测性、插件清单、六条逻辑链离线冒烟、故障模拟、迁移矩阵与恢复手册。

## 证据

- 定向验收测试：`74 passed`；独立审计扩大测试集：`148 passed`。
- 全量验证：`scripts/verify.py` 通过，`939 passed, 47 subtests passed`，编译、配置、网络默认值和 Agent 边界检查通过。
- `scripts/plugin_inventory.py` 可从 manifest 动态输出插件状态及能力。
- `scripts/flow_smoke_test.py` 的 `normal`、`plugin_unavailable`、`permission_denied`、`partial_failure` 四种场景均为 PASS，默认网络模式为 `OFF`。
- WP9 范围内 `git diff --check` 与新文件尾随空白检查通过；全局检查仍受工作区既有无关脏文件影响。

## 关键验收项

1. Flow、计划、策略、插件、部分结果和补偿事件均由真实运行边界发出，并携带 `correlation_id`。
2. WP9 事件使用字段白名单；EventBus 历史、订阅者和本地日志只接收安全快照。普通遥测故障不会改变业务结果，策略审计写入失败仍 fail-closed。
3. `partial_result` 使用真实步骤结果计数；只有实际调用补偿回调时才发出 rollback 事件。离线 fixture 的补偿明确标记为 `simulated`。
4. 六条 Flow 冒烟实际装配 ExperienceService、Planner、Executor、RuntimeKernel 和本地插件 fixture，不是静态输出。
5. 迁移矩阵保留旧入口，删除条件包含连续两个验收周期、等价测试、用户确认和独立删除计划。
6. Runbook 覆盖插件不可用、权限拒绝、部分失败、补偿、审计故障与代码回退。

## 评分

| 维度 | 得分 | 说明 |
|---|---:|---|
| 需求覆盖 | 20/20 | WP9 交付物和命令门槛齐全 |
| 架构边界 | 14/15 | 真实边界已接线；生产组装入口尚无强制统一注入点 |
| 权限安全 | 20/20 | 默认网络 OFF，审计 fail-closed，事件正文脱敏 |
| 测试质量 | 15/15 | RED 先行，覆盖异常 sink、权限、部分失败和补偿 |
| 用户阻力 | 10/10 | 一条命令 inventory，一条命令 smoke |
| 可解释与审计 | 8/10 | correlation 完整；partial 尚未单列 skipped |
| 可恢复 | 3/5 | 补偿只在真实回调时声明；失败步骤半副作用仍依赖插件实现 |
| 文档同步 | 2/5 | 三份 WP9 文档齐全；生产部署接线尚无独立装配文档 |
| **总分** | **92/100** | **PASS** |

## 非阻断保留项

- 事件 sink 注入是可选项；当前仓库没有统一生产组装入口可验证部署时必然接线。
- `partial_result.blocked_count` 合并了 blocked 与 skipped，合计正确但无法单独分析 skipped。
- rollback 为汇总事件；若插件在抛错前已产生局部副作用，执行器无法补偿该失败步骤，必须由插件契约和人工补偿清单处理。

这些保留项不得被解释为已完成生产级部署或任意外部写入的物理回滚能力。
