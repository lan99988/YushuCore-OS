# Plugin contract and development

## Package shape

Start with `templates/plugin-template` for a domain capability or `templates/app-plugin-template` for an app adapter. Keep packages independently installable and versioned. Core copies verified packages to `~/.yushuos/plugins/<plugin-id>/<version>` and treats that version as immutable.

A plugin includes `plugin.yaml`, `SKILL.md`, `README.md`, `run.py`, and its private `data/` directory. The manifest declares its stable ID and version, contract version, dependencies, data path, supported runtime, configuration, capability schemas, effects, intents, permissions, resource scopes, routes, and implementation/verification/authorization state. Keep credentials and remote resource IDs in local bindings, never in a distributable package.

## Runner protocol

Core starts the runner with one JSON request on stdin. The runner writes exactly one JSON result to stdout; diagnostics go to stderr. `yushuos_sdk` provides request/result types and a state store for shared receipts. The process receives a reduced environment, but plugins are trusted local code and are not OS-sandboxed.

For an external write, claim the original request ID with `StateStore.claim` before dispatch, then record a known result with `StateStore.record`. If a claim already exists, inspect its receipt. Leave uncertain results pending for readback. Keep private payloads out of workflow checkpoints.

## Build and install

1. Copy the template to a private working directory; set a unique plugin ID and version.
2. Implement the manifest, skill instructions, README, and JSON-stdio runner. Start read-only.
3. Create a package lock:

   ```bash
   yushuos lock-plugin --path ./my-plugin
   ```

4. Install the immutable package:

   ```bash
   yushuos install-plugin --path ./my-plugin
   ```

5. Check `yushuos catalog`. Installation does not grant permissions or silently activate a new version. If several versions are installed, select one in Core configuration. Check host disable state, dependencies, and authorization before relying on a route.
6. Add a narrow permission grant and shared ledger only for a documented write case. Preview before any authorized execution.

`plugin.lock.json` detects package drift; it does not authenticate the publisher or make untrusted code safe. Review plugin source before installation.

## Examples

See `templates/plugin-template/plugin.yaml` and `run.py` for the read-only example. `templates/project-contracts.example.yaml` shows project-scoped data contracts. Replace example IDs and schemas before publishing a plugin.
