# YushuOS Core 0.2.1

**A lightweight, host-independent kernel for a plugin-based personal AI system.** YushuOS Core catalogs available capabilities, routes structured requests to plugins, validates their JSON contracts, applies execution gates, tracks workflow receipts, and manages verified Core releases.

Core is the stable coordination layer. It does not try to become a finance app, CRM, task manager, or knowledge base. Domain rules and business data belong to separately installed plugins. WorkBuddy, Codex, or another AI host remains responsible for conversation and natural-language understanding.

[中文说明](#中文说明) · [Quick start](#quick-start) · [Capabilities](#capabilities) · [Install](docs/en/INSTALL.md) · [Usage](docs/en/USAGE.md) · [Plugin guide](docs/en/PLUGINS.md) · [AI installation](docs/en/AI-INSTALL.md)

## Capabilities

| Capability | What Core does |
| --- | --- |
| **Inspect the system** | `doctor` checks Core configuration and plugin manifests. `catalog` lists installed plugin versions, declared capabilities, routes, and current availability. |
| **Route declared capabilities** | `parse` checks explicit prefixes declared by plugins. The longest matching prefix wins; missing or ambiguous routes are reported instead of guessed. |
| **Validate plugin calls** | Checks structured JSON input and output against plugin schemas and verifies capability state, dependencies, resource scope, and permission requirements. |
| **Preview and govern execution** | Read-only calls and previews are the default. External writes require explicit user intent, a declared and verified capability, matching grants, a shared receipt ledger, and host execution authorization. |
| **Track multi-step work** | `plan` previews dependencies and expected changes; `workflow` can execute only when explicitly requested and every gate passes. `status` reads receipts and workflow state. |
| **Recover safely** | `resume` follows the original plan and recorded receipts. If a write result is unknown, Core requires a read-back using the original request ID instead of blindly replaying it. |
| **Manage plugin versions** | `lock-plugin` creates a SHA-256 package lock and `install-plugin` installs an immutable plugin version. Installation does not silently enable a plugin or select a version. |
| **Deploy Core releases** | `deploy --preview` stages a candidate, `verify` checks release files, `activate` switches the active version, and `rollback` restores a previously verified version. |
| **Connect supported hosts** | `install-host` and `uninstall-host` manage a thin Codex Skill or WorkBuddy Rule entry. They do not grant permissions or overwrite unmanaged files. |
| **Bridge separately installed apps** | `sync-app-plugin` can create an adapter for a separately installed IMA or Feishu app. The app package, account setup, resource bindings, and grants remain independent of Core. |

## Request flow

The AI host understands the user's words and chooses a candidate capability from the Core catalog. Core then validates and routes the structured request. A plugin owns the domain-specific behavior and data.

```text
User
  → AI host: understand intent and select a declared capability
  → Core: resolve plugin, validate contract, check gates
  → Plugin: preview or perform an authorized action
  → Core: return JSON and record minimal workflow receipts
  → AI host: present the result
```

For example, a host can use `catalog` to discover a read-only capability, submit a preview request, and show the result. A request to analyze finances or search personal notes works only if the corresponding domain plugin is separately installed, enabled, and configured. Core does not infer an unregistered provider from ordinary language.

## Quick start

Requires Python 3.11 or later.

```bash
git clone https://github.com/lan99988/Yushu2.0-OS.git
cd Yushu2.0-OS
python -m venv .venv
python -m pip install -e .
yushuos --help
yushuos doctor
yushuos catalog
```

The default Core home is `~/.yushuos`. For the complete Windows PowerShell and macOS/Linux setup, candidate deployment, verification, activation, and rollback steps, see the [installation guide](docs/en/INSTALL.md) or [安装指南](docs/zh-CN/INSTALL.md).

After installing the example plugin, check its explicit route and invoke it in preview mode:

```bash
yushuos parse --text "#example hello"
printf '%s' '{"request_id":"demo-read-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos invoke
yushuos status --request-id demo-read-001
```

The template is a starting point for plugin development; it is not a bundled domain application.

## Command groups

- **Inspect and route:** `doctor`, `catalog`, `parse --text ...`
- **Call and coordinate:** `plan`, `invoke`, `workflow`, `status`, `resume`
- **Package plugins:** `lock-plugin`, `install-plugin`
- **Deploy Core:** `deploy --preview`, `verify`, `activate`, `rollback`
- **Connect hosts:** `install-host`, `uninstall-host`
- **Adapt a separate app:** `sync-app-plugin --app ima|feishu`

Run `yushuos <command> --help` for the current flags. The [usage guide](docs/en/USAGE.md) and [使用指南](docs/zh-CN/USAGE.md) explain request formats, workflows, receipts, and write gates.

## Plugin and data boundaries

Plugins start from `templates/plugin-template` and declare their ID, version, capabilities, JSON schemas, routes, dependencies, permissions, resource scopes, runner, and private data path in `plugin.yaml`. The runner uses one JSON object on stdin and returns one JSON result on stdout through the `json-stdio-v1` protocol. See the [plugin guide](docs/en/PLUGINS.md) and [插件指南](docs/zh-CN/PLUGINS.md).

Plugin packages are versioned independently. Credentials and account/resource bindings stay in local configuration, not in distributable packages. Each plugin owns its private data directory; Core workflow checkpoints keep metadata and resource references rather than raw request bodies.

## What is included—and what is not

This repository ships the Core, SDK, templates, tests, and bilingual documentation. The example plugin is a scaffold, not a production domain module. Knowledge, finance, relationships, health, tasks, and other domain features require their own plugins and are not built into Core.

IMA and Feishu integrations are also separate app packages. This Core repository does not include their credentials, account configuration, or personal data; installing Core alone does not connect either service. Other AI hosts can use the generic CLI/JSON contract; only Codex Skill and WorkBuddy Rule have native host installers in this release.

Core does not perform OCR, manage CRM records, maintain a knowledge base, or provide a dashboard by itself. It does not replace the host's language model or ordinary natural-language understanding.

## Safety model and limits

- Writes fail closed unless explicit intent, plugin declaration and verification, permission grants, the shared receipt ledger, and host execute authorization all agree.
- Unknown write outcomes must be reconciled using the original request ID. Core does not blindly retry them.
- Plugin locks and release hashes detect package changes; they do not authenticate publishers or provide digital signatures.
- Plugins are trusted local code running as the current user. Environment reduction is useful isolation, but it is **not an operating-system sandbox**.

## Possible future directions

The project may add more portable plugins, external service adapters, controlled automation triggers, and specialized agents as real needs emerge. These are candidate directions only; they are not features delivered by Core 0.2.1 or promises of a delivery date.

## Documentation

- [Installation](docs/en/INSTALL.md) · [安装指南](docs/zh-CN/INSTALL.md)
- [Usage](docs/en/USAGE.md) · [使用指南](docs/zh-CN/USAGE.md)
- [Plugin contract and development](docs/en/PLUGINS.md) · [插件契约与开发](docs/zh-CN/PLUGINS.md)
- [AI host installation](docs/en/AI-INSTALL.md) · [AI 宿主接入](docs/zh-CN/AI-INSTALL.md)
- [Templates](templates/)

---

## 中文说明

**YushuOS Core 是一个轻量、跨宿主、由插件扩展的个人 AI 系统内核。**它维护插件能力目录，把结构化请求路由给插件，校验 JSON 契约和执行条件，跟踪工作流收据，并管理经过验证的 Core 发布版本。

Core 负责稳定的协调层，不把财务软件、CRM、任务管理器或知识库等领域业务塞进内核。领域规则和业务数据由单独安装的插件负责；WorkBuddy、Codex 等 AI 宿主负责对话与自然语言理解。

## Core 当前能做什么

| 能力 | Core 提供的功能 |
| --- | --- |
| **检查系统状态** | `doctor` 检查 Core 配置和插件清单；`catalog` 列出已安装插件版本、声明能力、路由和可用状态。 |
| **路由已声明能力** | `parse` 检查插件显式声明的前缀，优先匹配最长前缀；目标缺失或路由歧义时返回不可用或要求澄清，不猜测替代插件。 |
| **校验插件调用** | 按 JSON Schema 检查结构化输入与插件结果，并检查能力状态、依赖、资源范围和权限条件。 |
| **预览与执行治理** | 默认预览或只读。外部写入必须有明确用户意图、已声明且验证通过的能力、匹配权限、共享回执台账和宿主执行授权。 |
| **跟踪多步流程** | `plan` 预览步骤依赖和预期变更；只有用户明确要求执行且所有门禁通过时，`workflow` 才能执行；`status` 查询收据和流程状态。 |
| **安全恢复** | `resume` 依据原计划和已记录收据恢复。写入结果未知时，必须用原请求 ID 查询核对，Core 不盲目重放。 |
| **管理插件版本** | `lock-plugin` 生成 SHA-256 锁；`install-plugin` 安装不可变插件版本。安装不会静默启用插件或替用户选择版本。 |
| **部署与回滚** | `deploy --preview` 部署候选版本，`verify` 检查发布文件，`activate` 切换活动版本，`rollback` 恢复到之前验证通过的版本。 |
| **接入 AI 宿主** | `install-host` / `uninstall-host` 管理轻量 Codex Skill 或 WorkBuddy Rule 入口；不授予权限，也不覆盖非托管文件。 |
| **适配独立 App** | `sync-app-plugin` 可为单独安装的 IMA 或飞书 App 生成适配器。App 包、账号配置、资源绑定和权限仍独立管理。 |

## 一次请求如何工作

AI 宿主理解用户意图，并从 Core 能力目录中选择候选能力；Core 检查并路由结构化请求；领域插件执行对应业务并维护自己的数据。

```text
用户
  → AI 宿主：理解意图并选择已声明能力
  → Core：解析插件、校验契约、检查门禁
  → 插件：预览或执行获准操作
  → Core：返回 JSON 并记录最小化流程收据
  → AI 宿主：向用户呈现结果
```

例如，宿主可以通过 `catalog` 发现只读能力，提交预览请求并展示结果。分析财务或检索个人笔记，则必须先单独安装、启用并配置对应领域插件。Core 不会仅凭普通自然语言推测一个未注册的能力提供者。

## 快速开始

要求 Python 3.11 或更高版本。

```bash
git clone https://github.com/lan99988/Yushu2.0-OS.git
cd Yushu2.0-OS
python -m venv .venv
python -m pip install -e .
yushuos --help
yushuos doctor
yushuos catalog
```

Core 默认数据目录为 `~/.yushuos`。Windows PowerShell、macOS/Linux 的完整安装、候选版本部署、验证、激活和回滚步骤见[中文安装指南](docs/zh-CN/INSTALL.md)或[英文安装指南](docs/en/INSTALL.md)。

安装示例插件后，可检查显式路由并以预览模式调用：

```bash
yushuos parse --text "#example hello"
printf '%s' '{"request_id":"demo-read-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos invoke
yushuos status --request-id demo-read-001
```

示例插件只是开发起点，不是完整的领域应用。

## 常用命令

- **检查与路由：** `doctor`、`catalog`、`parse --text ...`
- **调用与编排：** `plan`、`invoke`、`workflow`、`status`、`resume`
- **打包插件：** `lock-plugin`、`install-plugin`
- **部署 Core：** `deploy --preview`、`verify`、`activate`、`rollback`
- **接入宿主：** `install-host`、`uninstall-host`
- **适配独立 App：** `sync-app-plugin --app ima|feishu`

使用 `yushuos <命令> --help` 查看参数。详见[使用指南](docs/zh-CN/USAGE.md)、[插件指南](docs/zh-CN/PLUGINS.md)和 [AI 宿主接入](docs/zh-CN/AI-INSTALL.md)。

## 插件和数据边界

从 `templates/plugin-template` 开始创建插件，并在 `plugin.yaml` 声明唯一 ID、版本、能力、JSON Schema、路由、依赖、权限、资源范围、运行器和私有数据路径。Runner 以 `json-stdio-v1` 协议通过 stdin 接收一个 JSON 对象，并在 stdout 返回一个 JSON 结果。详见[插件契约与开发指南](docs/zh-CN/PLUGINS.md)。

插件按独立版本安装。凭据、账号和资源绑定保存在本机配置，不放入可分发插件包。每个插件使用自己的私有数据目录；Core 流程检查点只保留元数据与资源引用，不保存原始请求正文。

## 当前仓库包含什么

本仓库包含 Core、SDK、模板、测试和中英文文档。示例插件是脚手架，不是可直接使用的领域模块。知识、财务、关系、健康、任务等能力须由各自插件提供，Core 本身不内置这些业务。

IMA 与飞书也以独立 App 包提供。本仓库不包含它们的凭据、账号配置或个人数据；单独安装 Core 不会连接这些服务。其他 AI 宿主可以使用通用 CLI/JSON 契约接入；当前版本只为 Codex Skill 和 WorkBuddy Rule 提供原生宿主安装器。

Core 不会自行 OCR 账单、维护 CRM 记录、管理知识库或提供仪表盘，也不替代宿主的大语言模型与自然语言理解。

## 安全模型与限制

- 外部写入必须同时满足明确意图、插件声明与验证、权限授予、共享操作回执台账和宿主执行授权；任一条件缺失都会阻止执行。
- 写入结果未知时，必须使用原请求 ID 核对；Core 不盲目重试。
- 插件锁和发布哈希可发现文件变动，但不验证发布者身份，也不是数字签名。
- 插件是以当前用户身份运行的本地可信代码。环境变量裁剪提供一定隔离，但**不等同于操作系统沙箱**。

## 后续方向（候选，不是交付承诺）

未来可根据实际需求扩展可移植插件、外部服务适配器、受控自动触发和专业 Agent。这些只是候选方向，不是 YushuOS Core 0.2.1 已交付的能力，也没有交付时间承诺。

## 文档

- [安装指南](docs/zh-CN/INSTALL.md) · [Installation](docs/en/INSTALL.md)
- [使用指南](docs/zh-CN/USAGE.md) · [Usage](docs/en/USAGE.md)
- [插件契约与开发](docs/zh-CN/PLUGINS.md) · [Plugin contract and development](docs/en/PLUGINS.md)
- [AI 宿主接入](docs/zh-CN/AI-INSTALL.md) · [AI host installation](docs/en/AI-INSTALL.md)
- [模板](templates/)
