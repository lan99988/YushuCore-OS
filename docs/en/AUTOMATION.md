# Automation, Events, and Execution History

This guide describes Core 0.3's local automation interface. Automation reuses installed plugins, Core execution gates, and the existing operations ledger. It does not include a cloud scheduler or bundle domain Apps or real accounts with Core.

## Install and isolated demo

Time-based triggers require the automation extra:

```powershell
python -m pip install -e ".[dev,automation]"
$demoRoot = Join-Path $env:TEMP ("yushuos-automation-demo-" + [guid]::NewGuid().ToString("N"))
python examples/automation-demo/setup.py --root $demoRoot
```

`setup.py` accepts only a new or empty directory and refuses non-empty roots, symbolic links, and junctions. It creates a dedicated config root, a separate Core ledger, three disabled rules, a v3 `demo.counter` plugin, and private action templates. The plugin writes only a local count inside the demo root; it configures no external account, credential, IMA, or Feishu connection. See “Run the demo” below.

Global CLI options go before the command:

```text
yushuos --config-root <root> [--project-file <file>] <command> ...
```

## Configuration and data locations

`automation.yaml` lives in the Core config root:

```yaml
schema_version: 1
timezone: Asia/Shanghai
history_retention_days: 30
```

`timezone` is the default for schedules that do not specify their own zone. `history_retention_days` accepts 1–36500 days and defaults to 90. `cron` triggers use traditional five-field cron. A nonexistent local time during a DST gap is skipped; an ambiguous time uses `fold=0`. `interval` triggers use an explicit UTC anchor and positive integer seconds. The default misfire policy is `skip`; `latest` catches up only when the latest occurrence is within the misfire window.

A rule action references only a plugin ID and action ref. Core reads strict JSON from `<config-root>/plugin-data/<plugin-id>/<manifest data_path>/actions/<action_ref>.json`, up to 128 KiB. Before registration, the action must pass the current CoreRuntime schema, dependency, permission, resource-scope, and shared-ledger gates. The template must not contain `request_id`. A simple action looks like:

```json
{
  "capability": "example.task.create",
  "intent": "capture",
  "fields": {"title": "Local demo task"}
}
```

A multi-step action can use a `steps` array. Each step needs `step_id`, `capability`, and `intent`; `fields`, `target`, and `depends_on` are optional. Business fields stay in the plugin-private directory. The automation SQLite database stores only action references, hashes, capability/provider pins, trigger metadata, statuses, and allow-listed resource references.

Minimal rule JSON:

```json
{
  "schema_version": 1,
  "id": "daily-review",
  "enabled": false,
  "trigger": {"type": "cron", "expression": "0 9 * * *", "timezone": "Asia/Shanghai"},
  "action": {"plugin_id": "example.tasks", "action_ref": "review"}
}
```

`trigger.type` may be `manual`, `event`, `cron`, or `interval`. Event triggers must specify an exact `source` and `event_type`; a plugin event uses the plugin ID as its source, while a manually published CLI event always uses `core.cli`. New rules are disabled by default. `automation add --file` registers the rule but does not enable or execute it.

Core stores rules, grants, events, and run metadata in `<config-root>/state/automation.sqlite`. The existing `<config-root>/operations.sqlite3` remains the SDK receipt and outbox ledger. The databases do not share a transaction. `automation.yaml` currently validates and exposes `history_retention_days`; the CLI does not run automatic history purging. After changes to settings, private action templates, or permission configuration, use `preview` to inspect gates and pins, then grant again as needed.

## Common commands

```powershell
# Register, list, and inspect; preview does not call the plugin

yushuos --config-root $demoRoot automation add --file "$demoRoot\rules\create.json"
yushuos --config-root $demoRoot automation list
yushuos --config-root $demoRoot automation show --rule demo-create
yushuos --config-root $demoRoot automation preview --rule demo-create

# Enable and grant separately; a grant lasts 30 days

yushuos --config-root $demoRoot automation enable --rule demo-create
yushuos --config-root $demoRoot automation grant --rule demo-create

# Run once and inspect history
yushuos --config-root $demoRoot automation run --rule demo-create --invocation-id tutorial-001
yushuos --config-root $demoRoot history list --rule demo-create
yushuos --config-root $demoRoot history show --run-id <run-id>
```

A grant binds the rule revision, action hash, provider digest, and capability/resource pins. Changes to the action, manifest, version, provider, or resource binding invalidate the old grant. Revoke a grant with `automation revoke --rule <rule-id>`. `automation disable` stops future triggers; it does not roll back an external operation that has already started.

**Manual execution:** use `automation run --rule <id> --invocation-id <stable-id>`. The invocation ID identifies one logical run for that rule/revision. Check history before retrying; do not use a new ID to bypass an unknown result.

**Host takeover:** if a pinned capability has `execution_mode: host_required`, an automated trigger creates a `host_pending` run and does not call the plugin in the Core background. A host can inspect and explicitly take over:

```text
yushuos --config-root <root> automation run --rule <id> --run-id <run-id> --host-mode execute
```

This restriction applies to the automation executor. The legacy manual `invoke` path keeps its existing call semantics and gates.

**Events:** a plugin may emit only manifest-declared events through SDK `record_with_events`. `automation tick` imports verified outbox events and processes event/schedule triggers:

```text
yushuos --config-root <root> automation tick
yushuos --config-root <root> events list
yushuos --config-root <root> events show --event-id <event-id>
```

A manually published event may specify only its type, allow-listed resource references, and optional ID. Core fixes its source to `core.cli`:

```json
{"id":"operator-note-001","type":"demo.review.requested","resource_refs":{"id":"demo-1"}}
```

Save the JSON to a file and run `events publish --file <file>`. The CLI cannot impersonate a plugin or select a plugin version. Event matching compares source, type, and project exactly.

**Scheduled worker:** `automation tick` executes one pass. `automation worker --max-ticks 10` polls once per second for at most ten passes. Without `--max-ticks`, it keeps running until Ctrl-C or process exit. Core does not configure operating-system autostart; configure and manage a service or scheduled task yourself if you need a persistent worker.

## Idempotency, leases, and history

Core constructs an occurrence key for every rule trigger: manual invocation ID, event ID, cron UTC time, or interval anchor/index. The run ID is derived from the rule ID, rule revision, and occurrence key using JCS. Each rule has at most one active run; its lease lasts 30 seconds and is renewed every 5 seconds. A worker has up to four parallel slots but will not execute the same rule concurrently.

Event chains are limited to depth 8 and each root event to fan-out 256. Work beyond a bound is not expanded. Outbox event IDs can be regenerated from the original request ID, emission index, and event type. Repeated ticks or imports do not duplicate the same event or occurrence.

Multi-step workflows use Core's existing dependency plan and receipt recovery, but they are not atomic across steps. After a failure or uncertain result, Core will not blindly run later external writes. `unknown` and `verification_pending` are never automatically replayed. After reading back the external result, explicitly resolve the original request ID:

```text
yushuos --config-root <root> history resolve --request-id <request-id> --outcome verified_success --reason-code remote_readback --evidence-ref <safe-reference>
```

`--outcome` may be `verified_success`, `verified_failed`, or `abandoned`; `actor` is always recorded as `core.cli`. `evidence-ref` is bounded reference metadata, not a place for credentials or business content. `abandoned` records that verification was abandoned but deliberately retains the original resource lock; it is not a safe retry state.

Filter with `history list --rule <id> --status <status>` and inspect a run with `history show --run-id <id>`. Each `tick`, including the worker’s non-executing poll, clears expired references according to `history_retention_days`: only terminal succeeded/failed/blocked/overlap_skipped/misfire_skipped runs and delivered-event resource references are eligible. Run/event deduplication identity tombstones remain. Active, unknown, verification-pending, and undelivered events are retained. Cleanup does not delete rows, plugin-private business data, or Core request receipts.

## Run the demo

The following commands touch only the dedicated root created by the setup script:

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

Expected flow: the first rule increments the local counter and records a receipt/outbox through one SDK ledger transaction. `tick` imports `demo.created` and triggers the second rule, whose action is a two-step read-only workflow. The final cron preview returns `status: preview` with `write_performed: false`. The demo does not connect to a real business service. For macOS/Linux, use the same demo in Bash or another POSIX shell:

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

## Optional: start the worker at user login

Core does not install or enable a background service. Configure one yourself only if a persistent worker is needed. Deploy and activate Core first; use the stable `<config-root>/bin/yushuos.py` launcher, which checks `active.json` and loads the selected verified release. The examples below use placeholder absolute paths—replace them with the Python executable and Core home on the target machine. Do not run more than one worker service for the same Core root.

### Windows Task Scheduler

1. Open Task Scheduler and choose **Create Task**. Set the trigger to **At log on** for the intended Windows user.
2. On **Actions**, choose **Start a program**. Set **Program/script** to the absolute venv interpreter, for example `C:\Users\Alice\.venvs\yushuos\Scripts\python.exe`. Set **Add arguments** to `"C:\Users\Alice\.yushuos\bin\yushuos.py" automation worker`. Set **Start in** to `C:\Users\Alice\.yushuos`.
3. In **Settings**, choose **If the task is already running: Do not start a new instance**. Run it as the intended user; elevated privileges are not needed for the local demo.
4. Start/stop it in Task Scheduler. Before upgrading Core, stop the task, let any active run finish or inspect its history, then deploy/activate the new release and start the task again.

### macOS LaunchAgent

Save a user LaunchAgent at `~/Library/LaunchAgents/com.yushuos.automation.plist`. Use absolute paths for both the stable Python interpreter and the Core launcher; this example starts at login and restarts the foreground worker if it exits:

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

Load and unload it for the current user session:

```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.yushuos.automation.plist"
launchctl kickstart -k "gui/$(id -u)/com.yushuos.automation"
launchctl bootout "gui/$(id -u)/com.yushuos.automation"
```

Run `bootout` before upgrading the active release; bootstrap it again after verification and activation.

### Linux systemd user service

Create `~/.config/systemd/user/yushuos-automation.service`. `%h` expands to the user home, and `ExecStart` calls the deployed Core launcher through a stable venv Python path:

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

Enable for the current user and stop it before upgrading:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yushuos-automation.service
systemctl --user status yushuos-automation.service
journalctl --user -u yushuos-automation.service
systemctl --user disable --now yushuos-automation.service
```

A user service starts with the user's systemd session. Enabling lingering changes that lifecycle; choose it explicitly only if boot-time operation without login is intended.

### Shared operating limits

The worker executes only rules that pass current grants and pins. A `host_required` run remains `host_pending`; no service or scheduler automatically grants it. Configure a separate explicit host handoff for that run. Keep the worker at one process per Core root; its internal worker pool may process different rules in parallel but never the same rule concurrently. Stop the worker before changing the active release. Lease expiry and fencing prevent stale work from taking a new lease, but cannot cancel an external request that was already dispatched or undo its side effect. For an uncertain write, inspect history and read back using the original request ID.
