# WP6 Plan / Review / Explore 验收报告

> 日期：2026-09-27
> 结论：PASS
> 分支：codex/yushu-wp6-six-flows
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP6 完成六条统一逻辑链，并接入 Goal、Project、Learning、Knowledge 四类能力插件。本轮只生成只读结果或待审提案，不执行项目、任务、日历或知识外写。

## 2. 交付物

- Goal：parse、current、gap、create_proposal。
- Project：list、context、create_proposal、milestone_proposal。
- Learning：current_state、progress、context；权威状态源由宿主只读注入。
- Knowledge：search、get、evidence_context，并保留 read_context、get_schema、health 兼容入口。
- Experience：新增 PlanFlow、ReviewFlow、ExploreFlow；公共 API 现导出六条 Flow。
- 新增四组插件测试、三组 Flow 测试与 Review/Explore 真实运行时 E2E。

## 3. Plan 验收

Plan 形成 Goal → Current State → Gap → Project → Milestone → Task → Calendar Proposal：

- goal.parse 首先验证最小目标；未提供优先级时显式标为 unspecified，不伪造优先级。
- 结构化项目分解只读取 request.context.project_plan；缺失时 needs_clarification，不让旧 Project builder 猜测。
- 单一 DAG 串联 goal.parse → project.create_proposal → project.milestone_proposal → task.create_proposal → calendar.create_proposal。
- 新项目的里程碑使用受控 project_proposal_id，不错误要求项目已预先登记。
- Task 输出使用 Today 可识别的标准字段；Calendar 与外部承诺始终待确认。
- 任务 evidence 仅含受控 project/task ID，不复制原始用户文本。

## 4. Review 验收

- 统一输出 Behavior → Result → Trend → Problem → Cause Hypothesis → Recommendation → Next Cycle。
- 原因只能作为假设；无证据的确定性 causes 被拒绝。
- ProjectPlugin 的 context envelope 与 Learning progress 的 completed/target 均有明确规范化。
- 空映射或未知形状不再形成“completed 空复盘”，而是 insufficient_review_evidence。
- Review next_cycle.after 可直接作为下一周期 Plan 的 review_input；Plan 校验 focus/period 并形成 next_cycle_context。

## 5. Explore 验收

- 只请求 knowledge.search，不直接导入或调用知识存储实现。
- KnowledgePlugin 的 search/get 全部经过注入的 Knowledge Gateway；PermissionDenied 与畸形返回稳定 fail-closed。
- 有时间范围的查询按授权节点 metadata created/updated 过滤；无日期证据的节点不被包装成指定周期结论。
- 每项 finding 包含 evidence、observed_at、time_range、confidence。
- 数据不足明确 needs_clarification；行动请求只提示转 Capture/Plan。

## 6. 兼容性与安全

- 恢复并测试旧 knowledge.read_context/get_schema/health capability；新增能力不破坏 Phase 7 MCP 集成。
- 插件 manifests 声明逐能力 permissions/effects；Goal、Project、Learning 保持 on-demand dormant。
- Project/Learning 的权威运行时数据必须由宿主注入；未配置时稳定报 unavailable，不生成替代事实。
- 默认 Presenter 不展示内部 capability 名称；审计仍只保存摘要。
- 外部写入、飞书写入、日历写入、消息发送：均为无。

## 7. TDD 与纠偏证据

- 四类插件初始 26 项以上 RED，随后专项转绿。
- Plan 初始缺模块 5 failed；能力命名、单 DAG、Review handoff 与新项目 milestone 引用均经历 RED→GREEN。
- Review/Explore 初始 9 failed；补齐后转绿。
- 独立测试审查发现手写假结果、Learning 输出未对齐、Knowledge 权限/畸形分支未覆盖；新增真实 Registry → Planner → Executor → Plugin → Flow E2E，并补齐 fail-closed 测试。
- 独立架构审查发现 Explore time_range 未真正过滤；KnowledgePlugin 现按节点日期过滤，缺时间证据时拒绝结论。
- 独立安全审查发现 Plan 将原始请求复制进任务 evidence；现改为受控 project/task ID。

## 8. 最终验证

- scripts/verify.py：841 passed、47 subtests passed，退出码 0。
- Review/Explore 真实插件运行时 E2E：2 passed。
- Knowledge + Explore 聚焦回归：35 passed。
- Goal + Plan 聚焦回归：15 passed。
- WP6 scoped git diff --check：通过。
- 全仓 git diff --check 仍受 WP0 前 body_os.py 尾随空白影响；未归因于 WP6，未改动该用户文件。

## 9. 设计性运行前提

- Goal、Project、Learning 默认按需休眠；宿主需在真实需求出现时激活。
- Learning 状态和 Project 复盘上下文没有现成权威持久源，必须由宿主注入只读 provider；缺失时流程会明确 partial/blocked。
- Experience Agent 的正式生产组装属于后续可观测性/运行收口；本轮已用真实 RuntimeKernel E2E 证明所需 permissions 和插件链可工作。

## 10. 回滚

回滚仅移除四个 WP6 插件包及 manifests 扩展、三条新 Flow、对应测试与本报告；不得删除 WP5 三条 Flow，不得覆盖 WP0 前已有修改。
