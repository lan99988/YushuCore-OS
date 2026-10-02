# YushuOS Core 0.2.1

**A small, host-independent core for personal AI systems.** It discovers versioned plugins, routes declared capabilities, validates JSON contracts, gates external writes, and records privacy-minimized receipts. Domain policy and business data stay in plugins.

[中文说明](#中文说明) · [Install](docs/en/INSTALL.md) · [Usage](docs/en/USAGE.md) · [Plugin guide](docs/en/PLUGINS.md) · [AI installation](docs/en/AI-INSTALL.md)

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

The default state directory is `~/.yushuos`. Install the host bridge only after deploying and verifying a release. See the [installation guide](docs/en/INSTALL.md) for Windows PowerShell and macOS/Linux commands.

## Architecture and boundaries

```text
AI host (natural-language intent and user interaction)
        │ JSON request / result
        ▼
YushuOS Core (registry, routing, schemas, execution gates, receipts)
        │ versioned JSON-stdio contract
        ▼
Independent plugins (domain rules, integrations, private plugin data)
```

Core is not a finance, CRM, task, or knowledge application. It does not infer a provider from an ambiguous request. Plugin installs are immutable and do not silently select a version. Business writes default to preview and require explicit user intent, a declared intent, verified and authorized capability, a matching permission grant, a receipt ledger, and host execution authorization. Unknown write outcomes are checked by their original request ID rather than replayed.

Plugins are trusted local code; subprocess environment reduction is not an operating-system sandbox. Read the [AI installation and safety guide](docs/en/AI-INSTALL.md) before connecting an agent or enabling writes.

## Documentation

- [Installation](docs/en/INSTALL.md) · [安装指南](docs/zh-CN/INSTALL.md)
- [Usage](docs/en/USAGE.md) · [使用指南](docs/zh-CN/USAGE.md)
- [Plugin contract and development](docs/en/PLUGINS.md) · [插件契约与开发](docs/zh-CN/PLUGINS.md)
- [AI host installation](docs/en/AI-INSTALL.md) · [AI 宿主接入](docs/zh-CN/AI-INSTALL.md)
- [Configuration templates](templates/)

## 中文说明

YushuOS Core 是一个轻量、与宿主无关的个人 AI 系统内核。它发现带版本的插件、路由已声明能力、校验 JSON 契约、管理外部写入门禁，并只保存经过最小化的操作回执。领域规则和业务数据由插件负责。

快速安装：Python 3.11+，克隆本仓库后运行 `python -m pip install -e .`，再执行 `yushuos doctor` 与 `yushuos catalog`。默认数据目录为 `~/.yushuos`。请先阅读[中文安装指南](docs/zh-CN/INSTALL.md)、[使用指南](docs/zh-CN/USAGE.md)、[插件开发指南](docs/zh-CN/PLUGINS.md)和 [AI 宿主接入指南](docs/zh-CN/AI-INSTALL.md)。

内核不代替财务、知识、任务或人际关系应用。写入默认预览；启用写入需要用户明确意图、已验证和已授权的能力、匹配的权限、操作回执台账及宿主执行授权。插件是本地可信代码，环境变量裁剪不等于操作系统沙箱。
