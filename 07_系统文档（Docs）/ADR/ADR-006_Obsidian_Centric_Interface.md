# ADR-006 Obsidian-Centric Human Interface

Date: 2026-08-05  
Status: Accepted  
Scope: Personal AI OS / Knowledge OS / Human Interface

## 决策

Personal AI OS 采用 **Obsidian-Centric** 架构：

> Obsidian 是个人认知系统的主要人类入口；Markdown Vault 是个人知识资产的唯一事实源；AI Runtime、Knowledge Gateway、llm_wiki 和 Feishu 都围绕该事实源提供受控能力。

```text
Human Owner
    ↓
Obsidian
    ↓
Personal Knowledge Vault
    ↓
Knowledge Gateway
    ↓
Personal Agent Runtime
    ↓
Agents / Tools / Models
```

Obsidian 是：

- Human Knowledge Interface
- Personal Cognitive Interface
- Markdown/YAML 编辑与审核入口
- Knowledge Graph / Backlinks / Canvas 的可视化入口

Obsidian 不是 Runtime、权限系统、审批引擎、调度器或模型路由器。

## 为什么这样设计

Personal Knowledge OS 的长期资产是 Markdown、YAML Metadata、链接、历史和人工判断。Obsidian 提供稳定的人类编辑、审阅、反向链接和图谱体验，同时保持知识资产可读、可迁移、可用 Git 管理。

## 为什么不采用其他方案

### 不采用“Obsidian 等于整个系统”

Agent 生命周期、权限判断、模型路由、工具调用、调度、审批和审计仍由 Runtime / Gateway 负责。全部塞进 Obsidian 插件会造成强耦合，并让系统依赖 Obsidian 进程才能运行。

### 不采用“llm_wiki 作为中心”

llm_wiki 是只读 Reader / Search / MCP Provider，不是长期事实源，也不负责 Human Approval 或 Agent Governance。

### 不采用“数据库作为中心”

SQLite、向量索引和其他数据库只能作为索引、缓存、搜索和分析层，不能替代 Markdown Vault。

### 不采用“Agent 直接操作 Obsidian 文件”

Agent 必须经过 Runtime、Permission Manager 和 Knowledge Gateway。知识变化必须走：

```text
Proposal → Human Review → Approval → Write
```

## 优点

- 人类拥有清晰、可见、可迁移的知识入口。
- Markdown Vault 保持 Source of Truth，便于 Git、备份和回滚。
- Obsidian 的链接、Graph、Canvas 和模板能力直接服务个人认知工作。
- AI 能力独立演进，不绑定 Obsidian 插件生命周期。
- llm_wiki、Feishu、移动端和未来工具都不会争夺事实源角色。

## 缺点

- Obsidian 不是服务端运行环境，自动化仍需要 Runtime / Scheduler。
- 移动端和远程访问需要额外 API 或同步策略。
- 大规模索引、向量检索和运行日志不能全部依赖 Obsidian UI。
- 插件生态变化可能影响编辑体验，必须保持 Markdown 保真。

## 不变量

- `D:\Personal_Knowledge_Vault` 是知识事实源。
- Obsidian 可以编辑和审核，但不能绕过 Proposal / Approval。
- Agent 不直接访问 Obsidian 文件或 Vault 路径。
- llm_wiki 只读，不修改 `llm_wiki.exe`，不成为事实源。
- Feishu 只负责 Task / Project / Schedule / Approval，不保存知识正文。
- Runtime state、Agent 日志、索引和缓存不替代 Vault。

## 未来如何演化

可以增加 Obsidian 社区插件、移动端、Web 入口、Knowledge Graph、RAG、Feishu Review 面板和 Personal Intelligence Engine，但必须保持：

```text
Human Interface
    ↓
Markdown Vault
    ↓
Gateway Boundary
    ↓
Runtime
```

