# Plugin contract and development

## Package shape

Start with `templates/plugin-template` for a domain capability or `templates/app-plugin-template` for an app adapter. Keep packages independently installable and versioned. Core copies verified packages to `~/.yushuos/plugins/<plugin-id>/<version>` and treats that version as immutable.

A plugin includes `plugin.yaml`, `SKILL.md`, `README.md`, `run.py`, and its private `data/` directory. The manifest declares its stable ID and version, contract version, dependencies, data path, supported runtime, configuration, capability schemas, effects, intents, permissions, resource scopes, routes, and implementation/verification/authorization state. Keep credentials and remote resource IDs in local bindings, never in a distributable package.

## Runner protocol

Core starts the runner with one JSON request on stdin. Contract v2 uses `json-stdio-v1`; contract v3 uses `json-stdio-v2`. The runner writes exactly one JSON result to stdout; diagnostics go to stderr. The `yushuos-core` distribution includes the `yushuos_sdk` import package for request/result types and shared state. The process receives a reduced environment, but plugins are trusted local code and are not OS-sandboxed.

For an external write, claim the original request ID with `StateStore.claim` before dispatch. Existing contract v2 plugins can keep recording known results with `StateStore.record`. Contract v3 plugins receive a runtime-validated immutable `PluginContext`; use it with `StateStore.record_with_events(result, context, emissions)` to record a confirmed receipt and declared outbox events atomically in the existing Core ledger. The runtime binds trusted context metadata to the invocation; constructing a dictionary yourself does not mint a trusted context. If a claim already exists, inspect its receipt. Leave uncertain results pending for readback. Keep private payloads out of workflow checkpoints.

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


## Contract v3 context and events

Manifest contract v3 requires `json-stdio-v2` and an exact context object. Import `PluginContext` from `yushuos_sdk` and validate the invocation envelope with `PluginContext.from_envelope(envelope)`. The immutable context binds the request ID, plugin ID/version, provider digest, project, existing ledger/data paths, allowed event names, automation run/root/causation/depth, and mode. Do not create or edit this context to claim another plugin identity.

Only emit event types declared in the manifest. After `claim(request)` returns true, call `record_with_events` once the result is known. The SDK commits the minimal receipt and outbox envelopes in the same existing Core ledger transaction. It emits successful business events only for a confirmed `succeeded` result and filters resource references. This does not make separate plugin file writes or multi-step Core workflows transactional.

## Independently installed Apps

A generic App release provides `release/app-descriptor.json` with `schema_version: 1`, `app`, `version`, and capability definitions. Each capability includes `id`, `effect`, `intent`, `input_schema`, `output_schema`, `execution_mode`, `auth: {required, scopes}`, and `resource_bindings`; `description` is optional. Descriptors contain portable policy metadata only, never credentials or local paths. Register an App with `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>`. New generic App IDs require a descriptor. Legacy IMA/Feishu releases without one remain supported.
