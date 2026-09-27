# ADR-010 Experience / Orchestration / Plugin Architecture

Date: 2026-09-26
Status: Accepted
Scope: Yushu-OS 下一阶段总体架构

## 背景

现有系统已经具备 Runtime、Agent、信息层、知识网关、个人智能、输入解析、每日排程和外部集成，但用户交互仍容易暴露后台模块，能力也缺少统一 Manifest、发现协议和跨领域编排合同。

历史文档中的“飞书 Base 为唯一事实源”也已不能准确描述当前系统：知识正文位于 D:\Knowledge，信息对象投影位于本地 SQLite，身体原始数据位于 Garmin 数据集。

## 决策

系统采用五层结构：

1. Experience Layer：Capture、Plan、Today、Adjust、Review、Explore。
2. Cognitive Core：身份、目标、上下文、约束、权限、决策与审计。
3. Orchestration Layer：意图、流程、能力计划、策略与执行。
4. Capability Plugin Layer：职责明确、可注册、可测试的能力单元。
5. Data / Integration Layer：飞书、Knowledge Gateway、information_system、Garmin、IMA 和文件。

采用联邦式事实源，并通过 Core 统一理解，不要求统一物理存储。

## 迁移策略

采用 Strangler Migration：

- 复用现有 Runtime、Gateway 和业务实现。
- 新插件首先是现有能力的适配器。
- 新旧路径以行为等价测试连接。
- 新路径稳定前不删除旧入口。
- 删除旧入口必须独立审批。

## 权限决策

Observe、Suggest、Autonomous、Approval Required 是动作权限，不是 Agent 自治等级。现有 Agent autonomy_level 上限继续保持 Level 2。

外部承诺、支付、消息、固定会议、不可逆操作和重大删除继续强制审批。

## 事实源裁决

- 飞书：执行态、任务、日历、承诺与移动触达。
- D:\Knowledge：知识正文、经验、方法与原则。
- information_system：信息对象结构化投影和领域观察。
- Garmin / Body Dataset：身体原始数据。
- Git 和本地配置：代码、契约与插件清单。
- Finance：月度快照，不建设逐笔流水。

本决策部分取代 DECISION_LOG D3 中“飞书为所有数据唯一事实源”的现行含义；D3 保留为历史记录。

本决策不取代 ADR-009。ADR-009 的 IMA + 飞书双持久化继续承载 cognitive_system 的认知资产投影和同步状态；D:\Knowledge 则是经 Knowledge Gateway 读取的长期知识正文权威。投影不得反向静默覆盖正文。

## 后果

正面：

- 用户按意图使用系统，不必理解模块。
- 后端能力可发现、可关闭、可测试和可审计。
- 不同事实源保持各自优势。
- 可以逐个迁移，不中断现有系统。

代价：

- 编排层和插件合同成为新的稳定接口。
- 需要维护事实源指针和跨层契约测试。
- 迁移期存在新旧两条入口，必须防止双写。

## 不变量

- 不新建平行 Runtime 或 Knowledge Gateway。
- network_mode 默认 OFF。
- Agent 不直接访问 Vault 或外部 API。
- Agent 自治等级不超过 Level 2。
- 高风险副作用必须审批。
- 旧入口在正式迁移验收前保留。
