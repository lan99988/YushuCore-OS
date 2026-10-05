# YushuOS Core 0.3.1

**A lightweight, host-independent kernel for a plugin-based personal AI system.** Core catalogs declared capabilities, routes structured requests to independently installed plugins, applies execution gates, tracks receipts, and manages verified Core releases. Core 0.3 adds local event-driven/scheduled automation and a descriptor-based adapter for independently installed Apps.

Core coordinates work; domain rules and business data belong to separate plugins or Apps. WorkBuddy, Codex, or another AI host handles conversation and natural-language understanding.

Version 0.3.1 adds nullable schemas and the opt-in `local_commit_v1` protocol for local business plugins: versioned request fingerprints, explicit recovery from private commit proofs, read-only result replay, and safe provider provenance. Existing plugins keep their previous protocol and fingerprint behavior. See the [plugin guide](docs/en/PLUGINS.md#local_commit_v1-local-commit-recovery).

[中文说明](#中文说明) · [Quick start](#quick-start) · [Automation demo](#automation-demo) · [Install](docs/en/INSTALL.md) · [Usage](docs/en/USAGE.md) · [Plugin guide](docs/en/PLUGINS.md) · [Core 0.3 handoff](docs/en/CORE-0.3-HANDOFF.md)

## Capabilities

| Capability | What Core does |
| --- | --- |
| **Inspect and route** | `doctor` checks configuration/manifests. `catalog` lists capabilities/readiness; `catalog --details` adds schemas, permissions, scopes, and execution mode. `parse` follows declared prefixes and reports ambiguity instead of guessing. |
| **Validate and execute** | Checks request/result contracts, plugin state, dependencies, resource scopes, permissions, and the shared receipt ledger. Writes require explicit intent and host authorization. |
| **Track and recover** | `plan` previews dependencies; `workflow` executes through existing gates. `status` and `resume` use original receipt identity. Unknown writes are never blindly replayed. |
| **Automate** | `automation` registers disabled rules, previews pinned actions, issues explicit 30-day grants, and runs manual/event/cron/interval occurrences. `events` and `history` inspect delivery and run metadata. See [Automation](docs/en/AUTOMATION.md). |
| **Manage releases** | `lock-plugin`/`install-plugin` verify immutable plugin packages. `deploy --preview`, `verify`, `activate`, and `rollback` manage Core releases. |
| **Connect hosts/Apps** | Host installers create thin Codex Skill or WorkBuddy Rule entry points. `sync-app-plugin` builds an adapter from a separately installed App's verified active release and App Descriptor. |

## Request flow

```text
User → AI host selects a declared capability → Core validates and checks gates
     → Plugin/App previews or performs an authorized action → Core records minimal metadata
     → AI host presents the result
```

A request works only when its provider is installed and available. Core does not infer an unregistered business provider from natural language.

## Quick start

Requires Python 3.11 or later. Install the `automation` extra for cron/interval scheduling:

```bash
git clone https://github.com/lan99988/Yushu2.0-OS.git
cd Yushu2.0-OS
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
# 可选：需要 cron/interval 调度时安装该 extra
python -m pip install -e ".[automation]"
yushuos --help
yushuos doctor
yushuos catalog
```

The default Core home is `~/.yushuos`. See the [installation guide](docs/en/INSTALL.md) for Windows PowerShell and macOS/Linux setup.

### Automation demo

Use a new, empty temporary config root; setup refuses non-empty directories and configures no real service or account. Replace `<demo-root>` with its path:

```text
python -m pip install -e ".[automation]"
python examples/automation-demo/setup.py --root <demo-root>
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/create.json
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/followup.json
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/schedule.json
yushuos --config-root <demo-root> automation preview --rule demo-daily-preview
yushuos --config-root <demo-root> automation enable --rule demo-create
yushuos --config-root <demo-root> automation grant --rule demo-create
yushuos --config-root <demo-root> automation enable --rule demo-on-created
yushuos --config-root <demo-root> automation grant --rule demo-on-created
yushuos --config-root <demo-root> automation run --rule demo-create --invocation-id demo-run-001
yushuos --config-root <demo-root> automation tick
yushuos --config-root <demo-root> events list
yushuos --config-root <demo-root> history list --rule demo-on-created
yushuos --config-root <demo-root> automation preview --rule demo-daily-preview
```

The first rule increments a local counter and atomically records a confirmed receipt with an event outbox item in the Core ledger. `tick` imports the event and runs a second rule's two-step read-only workflow; the cron example remains a preview. See [Automation guide](docs/en/AUTOMATION.md) for native commands on Windows, macOS, and Linux.

## Plugin and App boundaries

The scaffold in `templates/plugin-template` uses manifest `contract_version: 2` and `json-stdio-v1`. Contract v3 uses `json-stdio-v2` with an immutable validated plugin context. Both retain the Core Request/Result contract. Legacy manual invoke behavior remains compatible; automation `host_required` runs wait for explicit host takeover.

Plugins are independently versioned trusted local code. `plugin.lock.json` detects package changes, but does not authenticate publishers or create an OS sandbox. Keep credentials and resource bindings in local config. App adapters require an independently installed App; generic Apps provide `release/app-descriptor.json`. IMA/Feishu packages, credentials, accounts, and personal data are not bundled.

## Safety and limits

- Rules start disabled. Grants are separate, bind rule/action/provider pins, and expire after 30 days.
- Automation uses 30-second leases with 5-second heartbeats, one active run per rule, event depth up to 8, and fan-out up to 256 per root.
- Unknown writes require readback using the original request ID. Automation never blindly replays them; `abandoned` retains the resource lock.
- A workflow is not one cross-step transaction. SDK `record_with_events` atomically records a confirmed receipt and declared event outbox item in the existing Core ledger.
- Core does not configure OS-level worker autostart.

## Documentation

- [Installation](docs/en/INSTALL.md) · [安装指南](docs/zh-CN/INSTALL.md)
- [Usage](docs/en/USAGE.md) · [使用指南](docs/zh-CN/USAGE.md)
- [Automation](docs/en/AUTOMATION.md) · [自动化](docs/zh-CN/AUTOMATION.md)
- [Core 0.3 handoff](docs/en/CORE-0.3-HANDOFF.md) · [Core 0.3 对接说明](docs/zh-CN/CORE-0.3-HANDOFF.md)
- [Plugin contract](docs/en/PLUGINS.md) · [插件契约](docs/zh-CN/PLUGINS.md)
- [AI host install](docs/en/AI-INSTALL.md) · [AI 宿主接入](docs/zh-CN/AI-INSTALL.md)

---

## 中文说明

**YushuOS Core 0.3.1 是一个轻量、跨宿主、由插件扩展的个人 AI 系统内核。**它维护显式能力目录，将结构化请求路由到独立插件，校验契约与授权，跟踪收据，并管理经过验证的 Core 发布版本。0.3 增加本地事件/定时自动化，以及面向独立 App 的描述符适配入口。

Core 负责协调；领域规则和数据由单独安装的插件或 App 管理。WorkBuddy、Codex 等 AI 宿主负责对话和自然语言理解。

0.3.1 新增可空 Schema，以及本地业务插件可选的 `local_commit_v1` 协议：版本化请求指纹、依据私有提交证明显式恢复、只读结果重放和安全的插件来源信息。旧插件保持原协议及指纹行为，详见[插件指南](docs/zh-CN/PLUGINS.md)。

## Core 当前能力

| 能力 | Core 提供的功能 |
| --- | --- |
| **检查和路由** | `doctor` 检查配置/插件；`catalog` 列出能力和状态，`catalog --details` 增加 Schema、权限、资源范围、执行模式；`parse` 遵循显式前缀并报告歧义。 |
| **校验和执行** | 校验请求/结果、插件状态、依赖、资源范围、权限和共享台账。写入需要明确意图与宿主授权。 |
| **跟踪与恢复** | `plan` 预览依赖，`workflow` 沿用现有门禁，`status`/`resume` 使用原收据身份；未知写入不会盲目重放。 |
| **自动化** | `automation` 登记默认关闭规则、预览绑定、发放 30 天授权，并运行手动/事件/cron/interval occurrence。`events`/`history` 查询事件与运行元数据。详见[自动化指南](docs/zh-CN/AUTOMATION.md)。 |
| **管理发布** | `lock-plugin`/`install-plugin` 验证插件包；`deploy --preview`、`verify`、`activate`、`rollback` 管理 Core 发布。 |
| **连接宿主/App** | 宿主安装器创建 Codex Skill 或 WorkBuddy Rule 入口；`sync-app-plugin` 依据独立 App 的已验证活动版本和 Descriptor 生成适配器。 |

## 请求流转

```text
用户 → AI 宿主选择已声明能力 → Core 校验门禁
   → 插件/App 预览或执行获准操作 → Core 记录最小元数据 → AI 宿主呈现结果
```

请求只有在对应提供者已安装且可用时才能完成。Core 不会仅凭自然语言推测未注册的业务提供者。

## 快速开始

要求 Python 3.11+。需要 cron/interval 调度时安装 `automation` extra：

```bash
git clone https://github.com/lan99988/Yushu2.0-OS.git
cd Yushu2.0-OS
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
# 可选：需要 cron/interval 调度时安装该 extra
python -m pip install -e ".[automation]"
yushuos --help
yushuos doctor
yushuos catalog
```

Core 默认目录为 `~/.yushuos`。Windows PowerShell、macOS/Linux 安装见[安装指南](docs/zh-CN/INSTALL.md)。

### 自动化演示

使用新建的独立空临时配置根；脚本拒绝覆盖非空目录，不配置真实服务或账号。将 `<demo-root>` 替换为该目录：

```text
python -m pip install -e ".[automation]"
python examples/automation-demo/setup.py --root <demo-root>
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/create.json
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/followup.json
yushuos --config-root <demo-root> automation add --file <demo-root>/rules/schedule.json
yushuos --config-root <demo-root> automation preview --rule demo-daily-preview
yushuos --config-root <demo-root> automation enable --rule demo-create
yushuos --config-root <demo-root> automation grant --rule demo-create
yushuos --config-root <demo-root> automation enable --rule demo-on-created
yushuos --config-root <demo-root> automation grant --rule demo-on-created
yushuos --config-root <demo-root> automation run --rule demo-create --invocation-id demo-run-001
yushuos --config-root <demo-root> automation tick
yushuos --config-root <demo-root> events list
yushuos --config-root <demo-root> history list --rule demo-on-created
yushuos --config-root <demo-root> automation preview --rule demo-daily-preview
```

第一条规则增加本地计数器，并在 Core 台账事务内记录已确认收据和事件 outbox。`tick` 导入事件并运行第二条规则的两步只读流程；cron 示例保持预览。Windows、macOS 和 Linux 命令见[自动化指南](docs/zh-CN/AUTOMATION.md)。

## 插件与 App 边界

`templates/plugin-template` 使用 manifest `contract_version: 2` 与 `json-stdio-v1`；contract v3 使用带校验不可变 context 的 `json-stdio-v2`。两者沿用 Core Request/Result 契约。旧手动 invoke 行为保持兼容；自动化 `host_required` run 需宿主明确接管。

插件独立版本化，是当前用户身份运行的受信任本地代码。`plugin.lock.json` 可发现包变化，但不认证发布者，也不构成操作系统沙箱。凭据和资源绑定应保存在本地配置。App 适配器依赖单独安装的 App；通用 App 提供 `release/app-descriptor.json`。Core 不打包 IMA/飞书 App、凭据、账号或个人数据。

## 安全与限制

- 自动化规则默认关闭；授权单独授予，与规则/动作/provider pin 绑定，有效 30 天。
- 自动化使用 30 秒租约和 5 秒 heartbeat；每条规则最多一个活动 run；事件链深度上限 8、每个 root fan-out 上限 256。
- 未知写入须用原 request ID 核验；自动化不盲目重放，`abandoned` 会保留资源锁。
- 多步 workflow 不是跨步骤事务。SDK `record_with_events` 在既有 Core 台账事务内原子记录已确认收据与声明事件 outbox。
- Core 不配置操作系统级 worker 自启动。

## 文档

- [安装指南](docs/zh-CN/INSTALL.md) · [Installation](docs/en/INSTALL.md)
- [使用指南](docs/zh-CN/USAGE.md) · [Usage](docs/en/USAGE.md)
- [自动化指南](docs/zh-CN/AUTOMATION.md) · [Automation](docs/en/AUTOMATION.md)
- [Core 0.3 对接说明](docs/zh-CN/CORE-0.3-HANDOFF.md) · [Core 0.3 handoff](docs/en/CORE-0.3-HANDOFF.md)
- [插件契约](docs/zh-CN/PLUGINS.md) · [Plugin contract](docs/en/PLUGINS.md)
- [AI 宿主接入](docs/zh-CN/AI-INSTALL.md) · [AI host install](docs/en/AI-INSTALL.md)
