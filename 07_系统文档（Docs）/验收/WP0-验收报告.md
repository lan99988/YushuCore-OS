# WP0 基线与治理冻结验收报告

> 日期：2026-09-26
> 结论：PASS
> 分支：codex/yushu-wp0-governance
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 基线

执行前：

- Python：3.11.15。
- 全量测试：424 passed，47 subtests passed。
- scripts/verify.py：退出码 0。
- config/network.yaml：语义值 OFF；PyYAML 解析未加引号的 OFF 时返回 False，运行时和契约测试均做归一化。
- config/system.yaml：default_autonomy_level = 2。
- 工作区在执行前已有约 90 项未提交或未跟踪变化。

为避免继续在 main 上实现，创建分支 codex/yushu-wp0-governance。没有重置、清理或恢复任何用户已有文件。

## 2. 交付物

新增：

- PROJECT_CHARTER.md
- ARCHITECTURE_V2.md
- PLUGIN_STANDARD.md
- AUTONOMY_POLICY.md
- DOMAIN_REGISTRY.md
- ADR-010_Experience_Orchestration_Plugin_Architecture.md
- tests/test_architecture_contracts.py

最小修改：

- README.md
- SYSTEM_BLUEPRINT.md
- DECISION_LOG.md
- ADR-009_Knowledge_Storage_Dual_Persistence.md，仅追加 ADR-010 权威语义修订

## 3. 决策收口

- 六条用户逻辑链和五层架构已冻结。
- 旧“飞书唯一事实源”表述已从当前蓝图移除，D3 只保留为历史记录。
- D:\Knowledge 被明确为长期知识正文权威。
- ADR-009 的 IMA + 飞书双持久化被明确为认知资产投影、同步状态和检索副本，不得静默覆盖正文。
- runtime_core 的概念层归属已按 API 划分：context、permissions、approval 服务 Cognitive Core；kernel、router、scheduler 服务 Orchestration。
- Approval Required 被定义为动作策略，不提高 Agent autonomy_level。
- ADR-007 和 ADR-008 的 Proposed 状态未改变。

## 4. TDD 证据

RED 1：

- 首次运行 tests/test_architecture_contracts.py：6 failed，3 passed。
- 失败原因：五份治理文档与 ADR-010 尚不存在。

GREEN 1：

- 新建文档后：9 passed。

RED 2：

- 增加历史事实源、ADR-009 关系和入口文档 Token 契约后：3 failed，9 passed。

GREEN 2：

- 完成事实源说明和入口文档清理后：12 passed。

RED 3：

- 增加项目章程范围契约后：1 failed。

GREEN 3：

- 项目章程收敛为使命、用户价值、范围、非目标后：13 passed。

RED 4：

- 独立审查补充层映射、移动端触达和权限边界后：1 failed，13 passed。

GREEN 4：

- 完成文档与契约修正后：14 passed。

RED 5：

- 独立测试审查要求逐项锁定 Data / Integration 映射、公开接口依赖方向、事实源配对和 IMA 排除边界：1 failed，14 passed。

GREEN 5：

- 补齐架构表述和契约后：15 passed。

## 5. 最终验证

- tests/test_architecture_contracts.py：15 passed。
- 全量测试：439 passed，47 subtests passed。
- scripts/verify.py：439 passed，47 subtests passed，退出码 0。
- WP0 目标文件 scoped git diff --check：通过。
- README、SYSTEM_BLUEPRINT 和 WP0 新文档的敏感模式扫描：通过。

## 6. 已知工作区状态

全仓 git diff --check 仍会报告 handlers/body_os.py 的 CRLF/trailing-whitespace。该文件在 WP0 开始前已经处于修改状态，WP0 未编辑它；因此本报告使用目标文件 scoped diff 检查，不把用户既有变化归入 WP0。

仓库其他历史 Markdown 仍存在飞书 Base 资源标识。WP0 只移除了 README 和 SYSTEM_BLUEPRINT 两个当前入口中的内嵌值；全仓历史文档清理属于单独的安全迁移任务，不能在 WP0 中批量改写。

## 7. 回滚

WP0 没有运行时代码和外部写入。回滚只需移除六份新文档与契约测试，并撤销四个文档的 WP0 追加段落；不得回滚这些文件在 WP0 前已有的用户修改。

## 8. 外部副作用

- 外部写入：无。
- 飞书调用：无。
- Knowledge 写入：无。
- 配置变化：无。
