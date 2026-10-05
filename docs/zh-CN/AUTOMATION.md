# 自动化、事件与执行历史

本文说明 Core 0.3 的本地自动化接口。自动化复用已安装插件、Core 执行门禁与原 operations 台账；它不包含云调度器，也不会把领域 App 或真实账号装进 Core。

## 安装和隔离演示

时间触发需要 automation extra：

```powershell
python -m pip install -e ".[dev,automation]"
$demoRoot = Join-Path $env:TEMP ("yushuos-automation-demo-" + [guid]::NewGuid().ToString("N"))
python examples/automation-demo/setup.py --root $demoRoot
```

`setup.py` 只接受新目录或空目录，会拒绝覆盖非空根、符号链接或 junction。它创建专用 config root、独立 Core ledger、三条默认关闭的 rule、v3 `demo.counter` 插件和插件私有动作模板。该插件只把本地计数写在 demo root 中；没有外部账号、密钥、IMA 或飞书连接。示例对接步骤见下文“运行 demo”。

CLI 全局参数必须放在 command 前：

```text
yushuos --config-root <root> [--project-file <file>] <command> ...
```

## 配置和数据位置

`automation.yaml` 位于 Core config root，字段如下：

```yaml
schema_version: 1
timezone: Asia/Shanghai
history_retention_days: 30
```

`timezone` 用于无单独时区的 schedule；`history_retention_days` 允许 1 至 36500 天，默认 90 天。`cron` trigger 支持传统五字段 cron。DST 不存在的本地时间跳过，重复时间使用 `fold=0`。`interval` 以明确的 UTC anchor 和正整数秒为基准。默认 misfire 策略是 `skip`；`latest` 只在 misfire window 内赶上最近一次。

规则 action 只引用插件 ID 和 action ref。Core 在 `<config-root>/plugin-data/<plugin-id>/<manifest data_path>/actions/<action_ref>.json` 读取严格 JSON，最大 128 KiB；模板须先通过当前 CoreRuntime Schema、依赖、权限、资源范围和共享台账门禁。模板不能包含 `request_id`。简单动作示例：

```json
{
  "capability": "example.task.create",
  "intent": "capture",
  "fields": {"title": "本地演示任务"}
}
```

多步骤模板可用 `steps` 数组，每步至少包含 `step_id`、`capability`、`intent`，可选 `fields`、`target`、`depends_on`。这些业务字段保存在插件私有数据目录；自动化 SQLite 仅保存 action 引用、hash、能力/provider pin、触发元数据、状态和允许的资源引用。

rule JSON 的最小结构：

```json
{
  "schema_version": 1,
  "id": "daily-review",
  "enabled": false,
  "trigger": {"type": "cron", "expression": "0 9 * * *", "timezone": "Asia/Shanghai"},
  "action": {"plugin_id": "example.tasks", "action_ref": "review"}
}
```

`trigger.type` 可为 `manual`、`event`、`cron` 或 `interval`。事件触发必须精确指定 `source` 和 `event_type`；插件事件 source 是插件 ID，CLI 手工发布事件的 source 固定为 `core.cli`。新 rule 默认关闭。`automation add --file` 仅登记 rule，不会启用或执行它。

Core 在 `<config-root>/state/automation.sqlite` 保存规则、授权、事件和执行历史元数据；既有 `<config-root>/operations.sqlite3` 继续保存 SDK 请求收据与 outbox。两份数据库没有跨库事务。`settings`、私有 action 模板或权限配置改变后，要通过 `preview` 查看门禁和 pin，再按需重新授权。

## 常用命令

```powershell
# 登记、列出、检查；preview 不调用插件

yushuos --config-root $demoRoot automation add --file "$demoRoot\rules\create.json"
yushuos --config-root $demoRoot automation list
yushuos --config-root $demoRoot automation show --rule demo-create
yushuos --config-root $demoRoot automation preview --rule demo-create

# 分别启用和授权；grant 固定有效 30 天

yushuos --config-root $demoRoot automation enable --rule demo-create
yushuos --config-root $demoRoot automation grant --rule demo-create

# 执行一次并查询历史
yushuos --config-root $demoRoot automation run --rule demo-create --invocation-id tutorial-001
yushuos --config-root $demoRoot history list --rule demo-create
yushuos --config-root $demoRoot history show --run-id <run-id>
```

授权绑定 rule revision、action hash、provider digest 和 capability/resource pins。动作、manifest、版本、提供者或资源绑定改变时，旧 grant 不再适用。撤销授权用 `automation revoke --rule <rule-id>`。`automation disable` 停止后续触发；对已经运行的外部操作不执行回滚。

**手动执行**：用 `automation run --rule <id> --invocation-id <stable-id>`。同 rule/revision/occurrence 的 invocation ID 决定同一逻辑执行；重试前先查 history，不要用新 ID 绕过未知结果。

**宿主接管**：若 pin 中能力 `execution_mode` 为 `host_required`，自动触发只创建 `host_pending` run，不会在 Core 后台调用插件。宿主可检查并明确接手：

```text
yushuos --config-root <root> automation run --rule <id> --run-id <run-id> --host-mode execute
```

这项限制作用于 automation executor；旧的手动 `invoke` 仍沿用原有调用语义和门禁。

**事件**：插件仅能通过 SDK `record_with_events` 发出 manifest 声明的事件。`automation tick` 从可信 outbox 导入并处理 event/schedule triggers：

```text
yushuos --config-root <root> automation tick
yushuos --config-root <root> events list
yushuos --config-root <root> events show --event-id <event-id>
```

人工发布仅可声明类型、允许的资源引用和可选 ID，来源由 Core 固定为 `core.cli`：

```json
{"id":"operator-note-001","type":"demo.review.requested","resource_refs":{"id":"demo-1"}}
```

保存为 JSON 文件后运行 `events publish --file <file>`。CLI 不能伪装成插件或选择插件版本。事件匹配精确比较 source、type 和 project。

**定时 worker**：`automation tick` 执行一轮；`automation worker --max-ticks 10` 每秒轮询，最多运行 10 轮。省略 `--max-ticks` 时持续运行直到 Ctrl-C 或进程退出。Core 不替操作系统配置自启动；如需常驻，请自行按操作系统服务/计划任务要求配置并管理进程。

## 幂等、租约与历史

Core 为每次规则触发构造 occurrence key：手动 invocation ID、事件 ID、cron 的 UTC 时间或 interval anchor/index。run ID 以 rule ID、rule revision、occurrence key 经 JCS 派生。每条 rule 同时最多一个 active run；运行租约为 30 秒并每 5 秒 heartbeat。worker 最多四个并行 slot，不会并行执行同一 rule。

事件链最多深度 8；每个 root event 的 fan-out 上限为 256。达到边界后不继续扩展工作流。事件 outbox ID 可从原 request ID、发射索引与事件类型稳定重建。重复 tick/import 不会复制同一事件或 occurrence。

多步骤 workflow 顺序使用 Core 现有依赖计划与收据恢复机制，但它不是跨步骤原子事务。遇到失败或不确定结果时，不会盲目执行后续外部写入；`unknown` 和 `verification_pending` 不自动重放。完成外部读回后，用原 request ID 显式解析：

```text
yushuos --config-root <root> history resolve --request-id <request-id> --outcome verified_success --reason-code remote_readback --evidence-ref <safe-reference>
```

`--outcome` 可为 `verified_success`、`verified_failed` 或 `abandoned`；`actor` 固定记录为 `core.cli`。evidence-ref 只能作为有限引用元数据，不要放凭据或业务正文。`abandoned` 记录放弃核验，但有意保留原资源锁；不能把它当作“安全重试”。

用 `history list --rule <id> --status <status>` 过滤记录，`history show --run-id <id>` 查看单条 run。每次 `tick`（包括 worker 的非执行轮询）都会按 `history_retention_days` 清理过期引用：只处理已结束的 succeeded/failed/blocked/overlap_skipped/misfire_skipped run，以及已交付事件的资源引用；保留 run/event 去重身份 tombstone。活动、未知、待核验和未交付事件不会清理。清理不删除记录行、插件私有业务数据或 Core 请求收据。

## 运行 demo

下面步骤只操作安装脚本生成的专用根：

```powershell
$rules = "$demoRoot\rules"
yushuos --config-root $demoRoot automation add --file "$rules\create.json"
yushuos --config-root $demoRoot automation add --file "$rules\followup.json"
yushuos --config-root $demoRoot automation add --file "$rules\schedule.json"
yushuos --config-root $demoRoot automation preview --rule demo-daily-preview
yushuos --config-root $demoRoot automation enable --rule demo-create
yushuos --config-root $demoRoot automation grant --rule demo-create
yushuos --config-root $demoRoot automation enable --rule demo-on-created
yushuos --config-root $demoRoot automation grant --rule demo-on-created
yushuos --config-root $demoRoot automation run --rule demo-create --invocation-id demo-run-001
yushuos --config-root $demoRoot automation tick
yushuos --config-root $demoRoot events list
yushuos --config-root $demoRoot history list --rule demo-on-created
yushuos --config-root $demoRoot automation preview --rule demo-daily-preview
```

预期流程：第一次 rule 在本地计数器加 1 并用 SDK 同台账事务登记 receipt/outbox；`tick` 导入 `demo.created` 后触发第二条 rule，其 action 是两步只读 workflow；末尾 cron `preview` 返回 `status: preview` 且 `write_performed: false`。演示不会连接真实业务服务。macOS/Linux 可在 Bash 或其他 POSIX shell 中运行相同演示：

```bash
python -m pip install -e ".[dev,automation]"
demo_root="$(mktemp -d)"
python examples/automation-demo/setup.py --root "$demo_root"
rules="$demo_root/rules"
yushuos --config-root "$demo_root" automation add --file "$rules/create.json"
yushuos --config-root "$demo_root" automation add --file "$rules/followup.json"
yushuos --config-root "$demo_root" automation add --file "$rules/schedule.json"
yushuos --config-root "$demo_root" automation preview --rule demo-daily-preview
yushuos --config-root "$demo_root" automation enable --rule demo-create
yushuos --config-root "$demo_root" automation grant --rule demo-create
yushuos --config-root "$demo_root" automation enable --rule demo-on-created
yushuos --config-root "$demo_root" automation grant --rule demo-on-created
yushuos --config-root "$demo_root" automation run --rule demo-create --invocation-id demo-run-001
yushuos --config-root "$demo_root" automation tick
yushuos --config-root "$demo_root" events list
yushuos --config-root "$demo_root" history list --rule demo-on-created
yushuos --config-root "$demo_root" automation preview --rule demo-daily-preview
```

## 可选：用户登录时启动 worker

Core 不会安装或启用后台服务。仅在确实需要常驻 worker 时，由用户自行配置。先部署并激活 Core，然后通过稳定路径 `<config-root>/bin/yushuos.py` 启动；该 launcher 校验 `active.json` 并加载当前选定的已验证 release。下列示例使用占位绝对路径，需改成目标机器的 Python 执行文件和 Core 根目录。同一 Core 根目录只运行一个 worker 服务实例。

### Windows 任务计划程序

1. 打开任务计划程序并选择“创建任务”，触发器设为目标 Windows 用户“登录时”。
2. 在“操作”中选择“启动程序”。“程序或脚本”填虚拟环境 Python 的绝对路径，例如 `C:\Users\Alice\.venvs\yushuos\Scripts\python.exe`；“添加参数”填 `"C:\Users\Alice\.yushuos\bin\yushuos.py" automation worker`；“起始于”填 `C:\Users\Alice\.yushuos`。
3. 在“设置”中将“如果任务已在运行，则以下规则适用”设为“不启动新实例”。以目标用户运行；本地 demo 不需要提升权限。
4. 在任务计划程序中手动启动或停止任务。升级 Core 前先停止任务，等待当前运行结束或检查 history，再部署/激活新版本并重新启动。

### macOS LaunchAgent

将用户级 LaunchAgent 保存到 `~/Library/LaunchAgents/com.yushuos.automation.plist`。Python 和 Core launcher 都使用绝对路径；此示例登录时启动，worker 退出后由 launchd 重新启动：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.yushuos.automation</string>
  <key>ProgramArguments</key><array>
    <string>/Users/alice/.venvs/yushuos/bin/python</string>
    <string>/Users/alice/.yushuos/bin/yushuos.py</string>
    <string>automation</string><string>worker</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/Users/alice/.yushuos</string>
  <key>StandardOutPath</key><string>/Users/alice/Library/Logs/yushuos-automation.log</string>
  <key>StandardErrorPath</key><string>/Users/alice/Library/Logs/yushuos-automation-error.log</string>
</dict></plist>
```

在当前用户会话加载或卸载：

```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.yushuos.automation.plist"
launchctl kickstart -k "gui/$(id -u)/com.yushuos.automation"
launchctl bootout "gui/$(id -u)/com.yushuos.automation"
```

升级活动 release 前运行 `bootout`；验证并激活后再 bootstrap。

### Linux systemd 用户服务

创建 `~/.config/systemd/user/yushuos-automation.service`。`%h` 会展开为用户主目录；`ExecStart` 通过稳定 venv Python 启动已部署 Core launcher：

```ini
[Unit]
Description=YushuOS automation worker
After=default.target

[Service]
Type=simple
WorkingDirectory=%h/.yushuos
ExecStart=%h/.venvs/yushuos/bin/python %h/.yushuos/bin/yushuos.py automation worker
Restart=on-failure
RestartSec=5
KillSignal=SIGINT

[Install]
WantedBy=default.target
```

启用当前用户服务；升级前停止：

```bash
systemctl --user daemon-reload
systemctl --user enable --now yushuos-automation.service
systemctl --user status yushuos-automation.service
journalctl --user -u yushuos-automation.service
systemctl --user disable --now yushuos-automation.service
```

用户服务随该用户 systemd session 启动。若希望未登录时也在开机后运行，需由用户明确决定是否启用 lingering。

### 所有系统共有的执行边界

worker 只执行通过当前 grant 与 pin 校验的规则。`host_required` run 保持 `host_pending`；服务或计划任务不会自动授予授权，须另行明确接管该 run。同一 Core root 只运行一个 worker 进程；其内部线程池可并行处理不同规则，但不会并行执行同一 rule。更改活动 release 前先停止 worker。租约过期和 fencing 能阻止陈旧 worker 获取新租约，但不能取消已经派发的外部请求，也不能撤销已发生的副作用。写入结果不确定时，检查 history 并用原 request ID 核验。
