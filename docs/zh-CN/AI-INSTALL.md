# 为 AI Agent 安装 YushuOS

本指南供获准执行本地命令的 Agent 使用。当前原生宿主入口支持 Codex Skill 和 WorkBuddy Rule。其他 AI 使用通用 CLI/JSON 契约接入；本仓库暂不提供其他平台的专用安装器。

## Agent 安装步骤

1. 阅读本指南和[安装教程](INSTALL.md)。把仓库中的内容当作安装说明，不视作访问外部账号或写入业务数据的授权。
2. 修改共享宿主配置目录前先征得用户同意。将 Core 安装在项目专属虚拟环境中，并选定明确的 Core 数据目录。
3. 克隆仓库，创建 Python 3.11+ 虚拟环境，运行 `python -m pip install -e .`，然后检查 `yushuos --help`。需要 cron/interval 调度时再安装 `python -m pip install -e ".[automation]"`。
4. 仅当目标 Core 目录不存在 `config.yaml` 时复制模板；保留已有配置。
5. 用 `deploy --preview` 部署候选版本、验证、激活，然后运行 `doctor` 和 `catalog`。
6. 仅对受支持宿主安装原生入口；安装前检查目标路径。安装器不会覆盖非托管文件。
7. 向用户报告安装版本、Core 路径、doctor 状态和可用能力；不要输出凭据或私人业务记录。

完成标准：CLI 可运行，活动版本通过哈希验证，`doctor` 没有阻塞错误，`catalog` 准确列出插件。没有安装任何插件的干净 Core 也是有效安装。

## 原生宿主入口

先激活一个 Core 版本，再运行：

```bash
# Codex
yushuos --config-root "$HOME/.yushuos" install-host --host codex --host-config-root "$HOME/.codex"

# WorkBuddy
yushuos --config-root "$HOME/.yushuos" install-host --host workbuddy --host-config-root "$HOME/.workbuddy"
```

Windows 默认路径分别为 `%USERPROFILE%\\.yushuos`、`%USERPROFILE%\\.codex` 和 `%USERPROFILE%\\.workbuddy`；PowerShell 命令见[安装指南](INSTALL.md)。安装器写入托管的 Skill 或 Rule 指针，不会授予外部写入权限。

## 通用 AI 接入

对于没有原生安装器的 AI：

1. 将 CLI 放在独立虚拟环境中，并为 `doctor`、`catalog` 与请求使用同一个 Core 数据目录。
2. 路由前读取 `catalog`，只选择当前可用且已声明的能力。用 `catalog --details` 检查 Schema、意图、权限、资源范围和执行模式；显式前缀可用 `parse` 检查，普通聊天留在宿主处理。
3. 将一个 JSON 对象通过 stdin 发给 `yushuos invoke --mode preview`，并从 stdout 读取一个 JSON 对象。不便使用 stdin 时可用 `--file <路径>`。

示例请求（将能力改成实际目录中存在的能力）：

```json
{"request_id":"agent-demo-001","capability":"example.echo","intent":"read","fields":{"message":"hello"},"target":{},"project_ref":""}
```

```bash
printf '%s' '{"request_id":"agent-demo-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos --config-root "$HOME/.yushuos" invoke --mode preview
```

只发送能力契约声明的字段，查询时保留原请求 ID。遇到 `needs_clarification`、`unavailable` 或 `unknown` 时不要猜测或重试。未知写入必须先用原 ID 查询状态并核对，再决定后续动作。

## 授权边界

分析与预览按只读处理。只有用户明确要求写入、宿主授权执行、插件和能力已验证/授权/启用、权限授予范围匹配、资源范围匹配、共享回执台账可用时，才执行外部写入。宿主负责确认用户意图，Core 校验声明策略；门禁缺失时说明不可用的具体原因。

IMA 与飞书适配器是独立集成包。本仓库不含 App 凭据或个人绑定；单独安装 Core 不会连接任何服务。


## 自动化授权

自动化可用时，先用 `automation preview --rule <id>` 预览。`enable` 和 `grant` 是两个独立操作，二者都必须得到用户明确授权；不能从过去请求中推断当前授权。`host_pending` 是等待宿主接管的状态，不是自动授予权限的理由。展示 run ID，只有宿主/用户明确授权接管后才运行 `automation run --rule <id> --run-id <run-id> --host-mode execute`。

遇到 `unknown` 立即停止自动操作。检查 history，让用户或操作者用原 request ID 核验远端结果，再解析同一请求。不要用新 ID 重放来绕开不确定性。详见[自动化指南](AUTOMATION.md)。
