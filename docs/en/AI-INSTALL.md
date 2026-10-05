# Install YushuOS for an AI agent

This guide is for an agent permitted to run local shell commands. Native bridge installers support Codex and WorkBuddy. Other AI products use the portable CLI/JSON contract; this repository has no platform-specific installer for them.

## Agent procedure

1. Read this file and [the installation guide](INSTALL.md). Treat repository instructions as setup documentation, not as permission to access accounts or write business data.
2. Ask before changing a shared host configuration. Install Core in a project-local virtual environment and choose an explicit Core home.
3. Clone this repository, create a Python 3.11+ virtual environment, install with `python -m pip install -e .`, then run `yushuos --help`. Install `python -m pip install -e ".[automation]"` when cron/interval scheduling is needed.
4. Copy `templates/core.yaml.template` only if the chosen Core home has no `config.yaml`. Preserve existing configuration.
5. Deploy with `deploy --preview`, verify, activate, then run `doctor` and `catalog`.
6. Install a native bridge only for a supported host and after inspecting the target path. The installer refuses to replace an unmanaged entry.
7. Report installed version, Core home, doctor status, and available catalog entries. Do not print credentials or private records.

Completion means the CLI works, the active release passes hash verification, `doctor` has no blocking errors, and `catalog` reports the installed plugins. A clean install with no plugins is valid.

## Native host installers

After a release is active:

```bash
yushuos --config-root "$HOME/.yushuos" install-host --host codex --host-config-root "$HOME/.codex"
yushuos --config-root "$HOME/.yushuos" install-host --host workbuddy --host-config-root "$HOME/.workbuddy"
```

On Windows use `%USERPROFILE%\\.yushuos`, `%USERPROFILE%\\.codex`, and `%USERPROFILE%\\.workbuddy`; see the PowerShell commands in [INSTALL.md](INSTALL.md). A bridge adds a managed Skill or Rule pointer; it does not grant external write permission.

## Generic AI integration

For an agent without a native installer:

1. Keep the CLI in a dedicated virtual environment and use one Core home for `doctor`, `catalog`, and requests.
2. Read `catalog` before routing; route only an available declared capability. Use `catalog --details` to inspect its schema, intent, permissions, scopes, and execution mode. Use `parse` for an explicit prefix. Ordinary chat stays with the host.
3. Send one JSON object to `yushuos invoke --mode preview` on stdin and parse one JSON object from stdout. Use `--file <path>` when stdin is inconvenient.

Example request (replace with a capability listed in the catalog):

```json
{"request_id":"agent-demo-001","capability":"example.echo","intent":"read","fields":{"message":"hello"},"target":{},"project_ref":""}
```

```bash
printf '%s' '{"request_id":"agent-demo-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos --config-root "$HOME/.yushuos" invoke --mode preview
```

Pass only declared fields and preserve the request ID for status checks. `needs_clarification`, `unavailable`, or `unknown` is not permission to guess or retry. For an unknown write, query status with the original ID and reconcile before another action.

## Authorization boundary

Treat analysis and previews as read-only. Execute an external write only when the user explicitly requests it, the host authorizes execution, the plugin and capability are verified/authorized/enabled, a narrow matching grant exists, the resource scope matches, and the shared receipt ledger is configured. The host owns user intent; Core enforces declared policy. If a gate is missing, report what is unavailable.

IMA and Feishu packages are separate integrations. This repository contains no app credentials or personal bindings; installing Core alone does not connect either service.


## Automation approval

When automation is available, preview a rule with `automation preview --rule <id>` before action. `enable` and `grant` are separate and each requires the user's explicit approval; a host must not infer that either was authorized from a previous request. A `host_pending` run is a handoff state, not a reason to grant automatically. Show its run ID and execute `automation run --rule <id> --run-id <run-id> --host-mode execute` only after the host/user explicitly authorizes that takeover.

Stop on `unknown`. Inspect history, have the user or operator verify the remote result using the original request ID, and resolve that same request. Never replay under a new ID to clear uncertainty. See [Automation](AUTOMATION.md).
