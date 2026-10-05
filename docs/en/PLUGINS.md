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

## `local_commit_v1` local commit recovery

Only a contract v3 manifest may declare the top-level `operation_support: local_commit_v1`. The profile enables the explicit `invoke`, `replay`, and `recover` runner actions for the plugin's `internal_write` capabilities. A plugin may also expose `read_only` capabilities, but it cannot expose `external_write` capabilities under this profile. Plugins without the declaration keep the existing v2/v3 behavior and `Request.fingerprint()` algorithm.

For a local-commit write, Core validates the input schema and declared resource scopes, then returns a preview directly as `data: {capability, planned_fields, target, write_performed: false}`. Core does not start the runner, bind an operation context, claim the request, or create plugin data or ledger paths. The preview shows the validated input as received; it does not apply plugin defaults, trimming, or ID generation.

The v3 JSON envelope includes an `action` for this profile:

| Action | Purpose |
|---|---|
| `invoke` | First authorized execution. Claim with `StateStore.claim(request)`, then commit the business change and a local commit proof in one private transaction. |
| `recover` | Started only by explicit `resume --host-mode execute`. Check the original commit proof and use `reconcile_confirmed` to fill the Core receipt and event if it exists. Without proof, return unknown; never rerun the business operation. |
| `replay` | After current capability, permission, resource, and provider checks, read the original result snapshot from private storage without writing again. |

Profile context uses `schema_version: 2`, adding required `intent`, `operation_support`, and `fingerprint_scheme` fields to the v1 context. The v1 field set and `PluginContext.to_dict()` output remain unchanged. Core binds the original provider ID/version/digest, project, intent, and event trace. Recovery and replay reuse that identity; a provider version or digest change stops the operation.

Core selects and persists the fingerprint scheme. Plugins cannot choose or infer it from the hash. `legacy-v1` preserves `Request.fingerprint()` exactly. `jcs-operation-v1` computes SHA-256 over RFC 8785 JCS for `{capability, fields, target}` only. Core binds and checks `intent` and top-level `project_ref` separately. The shared helper is `yushuos_sdk.canonical.fingerprint_for_scheme(request, scheme)`; ordinary plugins call `StateStore.claim(request)` and the SDK reads the scheme from the Core binding.

When a plugin finds a matching committed proof in private storage, call `StateStore.reconcile_confirmed(request, result, context, emissions)`. In one Core ledger transaction, it appends an immutable confirmation and the event outbox. The original unknown receipt and any human resolution stay intact; conflicts and abandoned requests are rejected. Core stores no business body. If the saved body expired, return `succeeded` with `operation_status: committed`, `result_state: expired`, `code: task.result_expired`, `task_id`, and `original_request_id`; do not invent a `{task, changed}` result.

`StateStore.operation_context(request_id)` returns only Core-bound provider identity, original project/intent/trace, event declarations, operation profile, and fingerprint scheme. It omits paths, resource bindings, and business payloads. CLI `status` adds provider provenance and safe outbox resource references for schema v2 profile operations; legacy ledger output remains unchanged.

## Nullable schemas

An input or output schema may declare one concrete JSON type plus the string `null`, for example JSON `{"type":["string","null"]}`. A schema may also use JSON `{"type":"null"}` for values that must be null. Type arrays cannot contain multiple non-null types. A YAML null value is not a valid type name.

## Independently installed Apps

A generic App release provides `release/app-descriptor.json` with `schema_version: 1`, `app`, `version`, and capability definitions. Each capability includes `id`, `effect`, `intent`, `input_schema`, `output_schema`, `execution_mode`, `auth: {required, scopes}`, and `resource_bindings`; `description` is optional. Descriptors contain portable policy metadata only, never credentials or local paths. Register an App with `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>`. New generic App IDs require a descriptor. Legacy IMA/Feishu releases without one remain supported.
