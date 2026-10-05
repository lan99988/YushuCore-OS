# Personal system host rule

The host remains responsible for natural-language understanding and ordinary conversation. Route only registered personal-system capabilities through YushuOS Core. The Core selects a verified plugin and applies shared execution gates; each plugin owns its domain policy and data.

Keep legacy command prefixes on their existing compatibility route until a specific migration mapping has been registered. Do not infer a new App capability for an old prefix just because the names look similar.

Read `catalog --details` when selecting an existing capability; use its declared schema, intent, permission, resource scope, and execution mode. Plain `catalog` keeps its compatibility response.

For an automation rule, inspect `automation preview --rule <rule-id>` before any execution. Enabling a rule and granting its 30-day authorization are separate decisions and both require the user's explicit approval. Never grant automatically to clear `host_pending`. If a run is `host_pending`, show its run ID and wait for the host's explicit handoff using `automation run --rule <rule-id> --run-id <run-id> --host-mode execute`.

If an operation is `unknown`, stop automation, inspect history, and have the user or operator verify the external result using the original request ID before resolving it. Do not retry under a new request ID.

For reads, use the selected plugin's declared input contract. For writes, require an explicit user intent, preview first, and run only under the host's explicit execution authorization. Reuse the original request ID for status checks. Never blindly retry an unknown result. Keep private business content out of Core workflow checkpoints.
