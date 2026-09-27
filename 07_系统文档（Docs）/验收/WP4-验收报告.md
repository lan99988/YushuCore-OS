# WP4 第一批核心插件适配验收报告

> 日期：2026-09-26
> 结论：PASS
> 分支：codex/yushu-wp4-core-adapters
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP4 通过薄适配器把 Task、Calendar、Body、Information 四类既有能力接入 Capability Plugin、Registry、RuntimeKernel 和 Executor，不复制核心业务算法。所有变更保持外部写入关闭；Calendar 仅执行受网络模式约束的读取，变更类能力只生成待审提案。

本轮继续保留 WP0 前已存在的未提交变化，没有重置、清理或恢复用户文件。

## 2. 交付物

新增：

- capability_plugins/task/
- capability_plugins/calendar/
- capability_plugins/body/
- capability_plugins/information/
- capability_plugins/manifests/task.yaml
- capability_plugins/manifests/calendar.yaml
- capability_plugins/manifests/body.yaml
- capability_plugins/manifests/information.yaml
- tests/plugins/test_task_plugin.py
- tests/plugins/test_calendar_plugin.py
- tests/plugins/test_body_plugin.py
- tests/plugins/test_information_plugin.py
- tests/plugins/test_core_plugin_integration.py

扩展：

- capability_plugins/contracts.py
- capability_plugins/manifest.py
- capability_plugins/__init__.py
- runtime_core/kernel.py
- orchestration/executor.py
- 02_执行引擎（Engine）/每日排程引擎/calendar_sync.py
- 能力合同、Registry、Runtime、Executor 相关测试

## 3. 已冻结的能力与行为

### Task

- 提供 task.parse、task.list、task.create_proposal、task.update_proposal、task.prioritize。
- 解析与提案复用旧 Parser、lightweight handler 和 project execution builder。
- list/prioritize 通过显式注入 delegate 读取；输入和返回值均深拷贝，调用双方不能相互修改状态。
- create/update 只产出 pending_human_review 提案，不直接调用飞书或 lark-cli。

### Calendar

- 提供 calendar.list_events、calendar.find_free_slots、calendar.check_conflict、calendar.create_proposal、calendar.move_proposal。
- 生产旧模块接线必须使用 CalendarPlugin.from_legacy_module()；strict bridge 保证旧后端失败抛出受控异常，不会伪装成空事件、空时段或“空闲”。
- 读取只允许明确的 ASSIST 或 SYNC 网络模式；OFF、缺失或未知模式均在 delegate 调用前拒绝。
- 创建和移动仅生成提案，不执行事件写入。
- 显式 fixed_meeting、external_commitment 或 affects_commitment 标记会进入 Runtime 策略并要求人工审批。

### Body

- 提供 body.current_energy、body.recovery_context、body.training_context、body.adjustment_suggestion。
- 只消费注入 snapshot 或 snapshot_reader，不直接读取、改写 Garmin 三层文件，也不改变既有统计来源。
- 调整建议复用既有 body advisor；返回结构与缓存状态隔离。

### Information

- 提供 information.capture、information.recognize、information.get、information.list_inbox、information.propose_domain。
- 复用 InformationPipeline、InformationStore、recognizer 与 observer，不复制 InformationObject 或 DomainRecord。
- capture 明确标为 internal_write；查询能力为 read_only，不会因 SQLite 写声明被误判成外部副作用。

### 公共治理

- Manifest 支持 capability_permissions 与 capability_effects，权限和副作用按能力而非按整个插件计算。
- 四个核心 Manifest 对每一项 provides 都有完整策略映射。
- RuntimeKernel 以 Manifest 的能力级策略为可信来源；旧 Manifest 仍保留保守兼容路径。
- Executor 将 network_mode 传给插件，并保持旧只读插件在独立步骤失败后的继续执行语义。
- 四个适配器的底层异常均映射为稳定错误码并抑制 cause，任务原文、健康数据、日历后端信息和正文不会通过异常链暴露。

## 4. TDD 证据

主要 RED：

- 四个插件包不存在时，首批能力合同测试按预期失败。
- Task delegate 返回对象与 delegate 缓存共享，隔离测试先失败；加入返回值深拷贝后通过。
- 能力级权限/effect 字段不存在时，合同测试和 Kernel 最小权限用例失败；实现 Manifest 合同、加载和可信授权后通过。
- Calendar 缺 delegate 时返回普通失败对象，被 Executor 误记为 completed；改为受控异常后通过。
- Calendar 在 network_mode=OFF 时仍可调用 delegate；加入调用前门控后通过。
- 旧 calendar_sync 将查询失败转为空列表、None 或 ([], True)；真实 legacy bridge 回归先失败，加入兼容 strict 参数与 strict bridge 后通过。
- Executor 对固定会议提案硬编码 affects_commitment=False；审批用例先得到 completed，改为从冻结 payload 提取显式标记后通过。
- Information、Task、Body 包装异常保留底层 cause；脱敏测试先失败，改为 from None 后通过。
- Calendar 直接调用缺失 network_mode 时仍会读取；fail-closed 测试先失败，收紧为仅 ASSIST/SYNC 后通过。

## 5. 最终验证

- WP4 及 Capability/Runtime/Executor 关联测试：219 passed。
- scripts/verify.py：723 passed、47 subtests passed，退出码 0。
- WP4 scoped git diff --check：通过。
- calendar_sync.py 局部补丁 diff-check：通过。
- capability 漂移扫描：不存在遗留 information.ingest。
- 适配器异常链扫描：Task、Body、Information、Calendar 均无 from exc。
- 凭据扫描只命中测试中的虚构脱敏哨兵，未发现实际凭据。

## 6. 独立审查

- 架构与安全复审：初审发现 Information 能力漂移、插件级权限过宽、Calendar 失败哨兵、网络模式缺口和承诺标记未闭环；逐项修复后 PASS，最终关联测试 332 passed。
- Task/Body 测试充分性复审：初审发现 Task delegate 返回值别名；修复双向深拷贝和异常链脱敏后 PASS，66 passed、5 subtests passed。
- 差异与集成复审：初审发现 Task/Body cause 泄露风险；修复后 PASS，全量 723 passed、47 subtests passed，范围 diff-check 干净。

## 7. 已知非阻断项

- Calendar 的安全生产接线是 CalendarPlugin.from_legacy_module()；直接把原始 calendar_sync 模块传给通用 delegate 构造器不会自动增加 strict 包装，当前没有生产代码使用该路径。
- Task 已由独立复审手工验证 delegate 修改嵌套输入不会污染调用方；持久化自动回归目前重点覆盖返回值与 delegate 缓存隔离。
- Body 适配器按设计依赖外部提供 snapshot；真实 Garmin 数据采集与分层一致性仍由既有系统负责。

## 8. 外部副作用与回滚

- 外部写入：无。
- 飞书写入：无。
- 日历写入：无。
- 测试网络访问：无。
- Information 测试写入：仅 pytest 临时目录中的 SQLite。

回滚时只移除四个插件、四份 Manifest、WP4 测试、本报告及能力级策略扩展；calendar_sync.py 仅需撤销 strict 可选参数相关局部变更。不得覆盖其他工作包或 WP0 前已有的用户修改。
