# Changelog

本文件记录 Yushu-OS 面向用户和架构边界的版本变化。

## Yushu Adaptive OS v1.0 — 2026-09-27

### Added

- Capture / Plan / Today / Adjust / Review / Explore 六条用户逻辑链。
- Capability Plugin 合同、Manifest、Registry、生命周期、Planner 与 Executor。
- Task、Calendar、Body、Information、Goal、Project、Learning、Knowledge、Social、Life Admin、Finance、Creation、Interest、Experience 能力插件。
- 统一 Action Policy、审批闸门、仅元数据审计、`correlation_id` 事件链和离线恢复演练。
- 多证据 Personal Rule Candidate，支持审批、拒绝、撤销与置信度降级。
- 插件能力清单、六 Flow 冒烟、十个产品场景总验收和恢复 Runbook。

### Changed

- 前端从后台模块入口转为面向用户目标的六条逻辑链。
- 数据架构明确为联邦式事实源；知识正文、执行态、信息投影与身体原始数据各走受控边界。
- Capture 支持从“周五前交项目报告”这类单次自然语言输入提取普通任务与截止时间，并生成待审任务提案。

### Security

- 默认 `network_mode: OFF`；Agent 自治等级上限保持 2。
- 外部消息、外部承诺、固定会议变更、支付、投资和不可逆删除不自动执行。
- Runtime 事件与审计不记录凭证、知识正文、财务截图正文、健康原始数据或完整外部消息正文。

### Migration

- 继续保留 input_parser、daily_scheduler 与既有 handlers。
- 旧入口只有在连续两个验收周期、等价测试、用户确认和独立删除计划全部具备后才可删除。

### Verification

- `scripts/final_acceptance.py` 执行十个产品验收场景。
- `scripts/plugin_inventory.py` 输出插件状态与能力。
- `scripts/flow_smoke_test.py` 离线验证六条 Flow 及三类故障。
- `scripts/verify.py` 执行全量测试、编译、配置与架构边界检查。
- v1.0 冻结门禁结果为 `957 passed`、`47 subtests passed`；插件清单、四类 Flow smoke、十个产品场景及 `git diff --check` 全部通过。

### Release note

发布提交只纳入经过审查的实现、测试与文档白名单；工作区中无法安全归属的用户改动、运行数据和既有删除项均未混入。正式冻结由 annotated tag `yushu-adaptive-os-v1.0` 标识。
