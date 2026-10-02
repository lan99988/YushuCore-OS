# YushuOS Core V0.2

YushuOS is a small host-independent personal-system core. It catalogs portable plugin manifests, routes explicit capability prefixes, validates JSON contracts, gates writes, and records privacy-minimized workflow references. It intentionally does not own finance, knowledge, relationship, or other domain policy.

## Configure

Copy `templates/core.yaml.template` to `$YUSHUOS_HOME/config.yaml` (default: `~/.yushuos/config.yaml`). Keep credentials and private bindings outside plugin packages. Put plugins below `$YUSHUOS_HOME/plugins/<plugin-id>/<version>/`, or add explicit plugin roots in `plugins.plugin_paths`. A project may use `templates/project.yaml.template`; project configuration can select versions, providers, resources, disable plugins, and pass namespaced non-secret settings to a plugin. Project configuration cannot expand global permissions or execution modes.

## Package a plugin

Start from `templates/plugin-template`. Implement a `json-stdio-v1` runner and a strict `plugin.yaml`. Run `yushuos lock-plugin --path <plugin-directory>` after changes, then `yushuos install-plugin --path <plugin-directory>`. Installation does not enable the plugin or switch a selected version. The SHA-256 lock detects drift and accidental edits; it is not a signature or publisher identity.

## Commands

The deployed launcher is `$YUSHUOS_HOME/bin/yushuos.py`:

- `doctor`, `catalog`, and `parse --text ...` inspect configuration and route declarations.
- `invoke` previews by default. Writes require a declared intent, a verified/authorized manifest, a grant, an operation ledger, and explicit host execute mode.
- `plan` / `workflow` store step references only. `resume` requires an existing matching receipt-backed plan and never blindly retries an unknown result.
- `deploy --preview`, `verify`, `activate`, and `rollback` support candidate verification before changing the active release pointer.
- `install-host` installs a thin Codex skill or WorkBuddy rule at a caller-selected host directory. An existing unmanaged file is never overwritten; `uninstall-host` removes only an unchanged YushuOS-managed entry.

The subprocess receives only common runtime variables, not the caller's full environment. Plugins still run as trusted local code; this boundary is not an OS sandbox. Host and Core must both enforce authorization.
