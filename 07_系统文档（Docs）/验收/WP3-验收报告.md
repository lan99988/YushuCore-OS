# WP3 编排层骨架验收报告

> 日期：2026-09-26
> 结论：PASS
> 分支：codex/yushu-wp3-orchestration
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP3 将结构化输入或自然语言意图转换为六条用户逻辑链之一，再通过 Registry 生成能力执行计划，并由 RuntimeKernel 的统一策略边界完成 dry-run 或仅限已授权内部能力的执行。本轮不接入真实领域插件，不启用任何真实外部写入。

本轮继续保留 WP0 前已存在的未提交变化，没有重置、清理或恢复用户文件。

## 2. 交付物

新增：

- orchestration/__init__.py
- orchestration/contracts.py
- orchestration/errors.py
- orchestration/intent_router.py
- orchestration/flow_registry.py
- orchestration/planner.py
- orchestration/executor.py
- tests/test_orchestration_contracts.py
- tests/test_intent_router.py
- tests/test_capability_planner.py
- tests/test_orchestration_executor.py

## 3. 已冻结的行为

- FlowName 仅包含 Capture、Plan、Today、Adjust、Review、Explore 六条逻辑链。
- IntentRouter 优先接受显式结构化 flow，其次使用可测试规则，最后才调用可注入分类器；测试不依赖网络或真实模型。
- 未识别、低置信度和低置信度高风险输入返回 ClarificationRequest，不静默猜测。
- 一次输入只有一个主逻辑链；次级动作留给能力步骤表达。
- CapabilityCall 对 payload 建立递归不可变、JSON-compatible 的独立快照，并拒绝 NaN 与正负无穷。
- ExecutionPlan 校验 flow 一致、step_id 唯一、依赖存在且图无环。
- CapabilityPlanner 的请求不携带 plugin_id；provider 只能由 PluginRegistry 的 ready Manifest 解析。
- 缺失能力、provider 未就绪、未知依赖、环成员和被环阻塞步骤均返回明确 gap，不静默丢步骤。
- 环检测使用 Tarjan 强连通分量，精确区分实际环成员与下游阻塞节点。
- Executor 默认 dry-run；dry-run 产生策略判断和预期变更但绝不调用插件。
- 非 dry-run 也必须先经 RuntimeKernel.authorize_action；待审批或拒绝动作不会调用插件。
- 计划中的 provider 必须与 Registry 解析结果一致；注入执行器的完整 Manifest 也必须与 Registry 权威 Manifest 相等。
- 插件收到的是 payload 的独立可变副本，不能修改冻结计划。
- 步骤失败时跳过依赖步骤；独立只读步骤可继续；存在成功与失败/阻断时总体状态为 partial。
- 插件异常正文不会进入执行结果；仅保留受控 error_code。

## 4. TDD 证据

主要 RED：

- orchestration 包不存在时，合同、路由、Planner 和 Executor 测试均因缺模块失败。
- Executor 缺失时 5 个核心执行用例先失败。
- 公共 __init__ API 测试最初因无导出失败。
- 伪造计划 provider 最初只得到泛化 authorization_failed；专门的 provider mismatch 测试先失败。
- payload 可原地修改、环下游误报为环成员两项测试先失败。
- 交叉边强连通分量漏判测试先失败，推动普通 DFS 改为 Tarjan SCC。
- 注入插件 Manifest 与 Registry Manifest 的 writes 不一致时最初仍会执行；可信边界测试先失败。
- NaN 与正负无穷最初可进入 payload；3 个严格 JSON 用例先失败。
- 冻结后的非空嵌套 payload 使用 deepcopy 时真实执行失败；端到端非空调用测试先失败。

对应 GREEN：

- 完成严格合同、六链规则路由、Registry-only Planner 与策略执行器后，基础 WP3 测试通过。
- 增加 provider 双重绑定、完整 Manifest 相等校验后，两类 provider 欺骗均在插件调用前阻断。
- 使用递归冻结容器和 Tarjan SCC 后，计划不可变且 gap 分类精确。
- 使用显式递归解冻副本替代 deepcopy 后，非空 payload 可执行且计划不被插件修改。

## 5. 最终验证

- 四份 WP3 专项测试：54 passed。
- scripts/verify.py：649 passed、47 subtests passed，退出码 0。
- orchestration compileall：通过。
- WP3 scoped git diff --check：通过。
- WP3 范围扫描未发现网络或子进程调用。
- 端到端手工/自动场景：Today 输入 → IntentRouter → CapabilityPlanner → Executor dry-run，策略允许只读步骤且插件调用次数为 0。

## 6. 独立审查

- 架构与安全复审：初审复现注入执行器 Manifest 欺骗；修复并补测后 PASS，定向测试 82 passed。
- 测试充分性复审：先后发现 payload 内部可变、环下游误报、交叉边 SCC 漏判、非有限浮点；逐项 TDD 修复后 PASS，WP3 关联测试 53 passed（最终又增加非空 payload 回归后为 54 passed）。
- 差异与集成复审：复现 frozen payload deepcopy 回归；修复后最终 PASS，全量 649 passed、47 subtests passed。

## 7. 已知非阻断项

- 规则路由仍是启发式；复杂多意图输入可能需要后续本地分类后端补强，但低置信度不会静默执行。
- Manifest 一致性验证不是代码沙箱；接入的插件实现仍属于受信任代码，WP4 必须继续只做旧能力适配。
- dry-run 会留下 Kernel 元数据审计记录，但不会调用插件或产生外部业务副作用。
- Planner 当前按请求与依赖生成计划，不负责领域级任务分解；该逻辑由 WP4 适配器和 WP5 逻辑链逐步提供。

## 8. 外部副作用与回滚

- 外部写入：无。
- 飞书调用：无。
- Knowledge 写入：无。
- 网络访问：无。

回滚仅需移除 orchestration、四份 WP3 测试与本报告；不得覆盖其他工作包或 WP0 前已有的用户修改。
