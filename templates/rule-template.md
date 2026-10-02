# Personal system host rule

The host remains responsible for natural-language understanding and ordinary conversation. Route only registered personal-system capabilities through YushuOS Core. The Core selects a verified plugin and applies shared execution gates; each plugin owns its domain policy and data.

Keep legacy command prefixes on their existing compatibility route until a specific migration mapping has been registered. Do not infer a new App capability for an old prefix just because the names look similar.

For reads, use the selected plugin's declared input contract. For writes, require an explicit user intent, preview first, and run only under the host's explicit execution authorization. Reuse the original request ID for status checks. Never blindly retry an unknown result. Keep private business content out of Core workflow checkpoints.
