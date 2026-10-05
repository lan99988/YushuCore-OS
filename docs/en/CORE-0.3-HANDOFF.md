# YushuOS Core 0.3 Integration Notes (Contract v1.1)

This handoff is for plugin and independently installed App maintainers. It describes Core 0.3 compatibility boundaries, the API v2 plugin protocol, SDK event delivery, and automation integration. Core provides a local capability catalog, validation, and authorization boundary. Domain behavior and account data remain in independently installed plugins or Apps.

## Compatibility boundaries

The existing CLI commands `doctor`, `catalog`, `parse`, `plan`, `invoke`, `workflow`, `status`, and `resume` retain their default JSON shapes and call behavior. Only `catalog --details` adds descriptions such as input/output schemas, intents, permissions, resource scopes, and `execution_mode`; plain `catalog` keeps its existing shape. Put global `--config-root` and `--project-file` options before the command.

Existing manifest `contract_version: 2` plugins continue to use the `json-stdio-v1` runner, while the structured Core API v2 Request/Result contract stays stable: Core sends one JSON envelope on stdin, and the plugin returns one JSON result on stdout. Results may contain only `status`, `request_id`, `message`, `resource`, `data`, and `error`. Core checks status, request ID, field types, and the declared output schema. Unknown fields or mismatched results are rejected. The new automation `host_required` restriction applies to automated execution and does not change the legacy manual `invoke` path.

Manifest contract v3 uses the `json-stdio-v2` runner and adds a required immutable `context`, while preserving the Core API v2 Request/Result field contract. `PluginContext.from_envelope()` validates the exact field set, plugin/request identity, provider digest, event declarations, depth, and resource map, then recursively freezes its values. The Core runtime binds the trusted context to the invocation; a plugin-created dictionary cannot replace that binding. Existing v2 plugins may continue without this context.

## SDK, ledger, and events

`Request`, `Result`, and the SDK are included in the `yushuos-core` distribution and imported from `yushuos_sdk`; do not install a separate `yushuos-sdk` distribution. Automation action templates describe only capability, intent, fields, optional target, and workflow steps; they must not contain `request_id`. Core derives a stable request ID for each step from its `run_id` and `step_id`, so the same occurrence reuses the same ID.

Action hashes, rule revisions, authorization bindings, and stable run and step-request IDs use SHA-256 over RFC 8785 JCS bytes. The exact formulas are:
- run_id = "run-" + SHA-256(JCS({"kind":"run-v1","rule_id":rule_id,"rule_revision":revision,"occurrence_key":occurrence_key}))
- request_id = "req-" + SHA-256(JCS({"kind":"step-v1","run_id":run_id,"step_id":step_id}))
Both digests are lowercase hexadecimal. The SDK outbox event ID is a separate deterministic SHA-256: it hashes UTF-8 JSON for {"request_id":request_id,"index":emission_index,"type":event_type}, serialized with ensure_ascii=False, sorted keys, and compact separators. Outbox event IDs are not JCS digests. A root event has depth 0; an emission caused by an event-driven run uses its causation depth plus 1.

A plugin provider_digest covers an object containing kind: provider-v1, plugin ID, version, and the SHA-256 hash of each actual package file. Core rechecks plugin.lock.json against disk before computing the digest and refuses a mismatched package. These automation identifiers do not change legacy API v2 request fields or default responses.

A plugin calls `StateStore.claim(request)` before dispatch and calls `record_with_events(result, context, emissions)` once the result is known. The SDK publishes declared events only after a confirmed `succeeded` result. The SDK writes a minimal receipt and event outbox envelopes in **one transaction in the existing Core operations SQLite ledger**. Event IDs are deterministic from the original request ID, emission index, and event type. Event types must be declared by the manifest, and resource data is limited to allow-listed references. Unknown, failed, or partial results do not publish successful business events. This transaction covers the receipt and outbox, but does not include plugin-private file writes or the separate automation SQLite database. An external App provider fingerprint includes App file hashes, external-binding metadata, and the config-file SHA, but excludes absolute paths and config contents. Moving an installation does not change the fingerprint; changing same-version code or configuration invalidates the old grant.

Trusted context supplies event source plugin/version, project, request, causation, root, and occurrence metadata. CLI-published events can use only the `core.cli` source; a caller cannot impersonate a plugin. Before importing plugin outbox events, `automation tick` checks the source plugin, declared event, version, and provider digest. Stable event IDs make repeated imports idempotent. Core does not provide a single transaction across a multi-step workflow.

## Automation identity and execution boundaries

Each trigger occurrence has a stable key: a manual invocation ID, an event ID, a cron UTC scheduled instant, or an interval anchor and index. A run ID is derived from the rule ID, rule revision, and occurrence key. The same occurrence cannot create a second run, and each rule has at most one active run at a time.

Runs use a 30-second lease renewed every 5 seconds. A worker may run different rules concurrently, while duplicate work for the same rule is blocked. Event chains have a maximum depth of 8 and a fan-out limit of 256 per root. Unknown results are never replayed automatically: read back using the original run/request identity. `abandoned` records an explicit decision and retains the resource lock. Automation history stores bounded metadata, hashes, pins, statuses, and resource references, not action field contents or workflow payloads.

Automation stores rules, grants, events, and runs in the separate `<config-root>/state/automation.sqlite` database. The existing Core `operations.sqlite3` remains the ledger for plugin request receipts and outbox events. Rules reference action templates stored under the plugin-private data directory at `actions/<action_ref>.json`; the database stores the reference, hashes, and provider pins. `automation.yaml` accepts `schema_version: 1`, a timezone, and a history retention period. See the [Automation guide](AUTOMATION.md).

## Generic App Descriptor v1

Independently installed App packages are not shipped with Core. An App release may provide `release/app-descriptor.json` with top-level `schema_version: 1`, `app`, `version`, and `capabilities`. Each capability declares a unique ID, `effect`, `intent`, input/output schemas, `execution_mode`, `auth.required` and scopes, and `resource_bindings`; it may also include a description. The descriptor is portable policy metadata and must not contain credentials, tokens, account data, or local paths.

Run `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>` to create an immutable Core adapter from the verified active release and write its managed binding. A new generic App ID requires a descriptor. Existing `ima` and `feishu` packages without a descriptor continue through their legacy protocol. A generic App adapter with a descriptor uses contract v3 and `json-stdio-v2`; the App CLI still reads the original request from stdin and may read the JSON context from `YUSHUOS_PLUGIN_CONTEXT` for SDK validation and receipt/event handling. Account credentials, release details, and the shared ledger are managed by the App's local active pointer, outside the descriptor and Core package.

## Release acceptance checklist

- Keep the default v2 CLI, catalog JSON, and plugin request/result shape stable; select expanded catalog fields only with `catalog --details`.
- Emit declared events only after confirmed success, and use the SDK to write the receipt and outbox to the existing Core ledger together.
- Bind automation grants to the rule revision, action hash, provider digest, and resource pins. Grants expire after 30 days; review and grant again after any binding changes.
- Automated `host_required` actions enter `host_pending` until a host explicitly takes over. The legacy manual `invoke` path is unaffected by this automation wait state.
- For an `unknown` write, first read back the external result using the original request ID, then append a verification decision with `history resolve`; do not submit a duplicate with a new request ID.
- App packages, IMA/Feishu services, real accounts, and real data are not included in the Core repository or the local demo.
