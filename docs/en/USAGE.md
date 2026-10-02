# CLI and daily use

## Routing model

The AI host understands ordinary language and owns the conversation. It reads the Core catalog, routes only a declared capability, and sends a contract-compliant JSON request. Core resolves the plugin version, validates inputs, enforces execution gates, and returns a JSON result. Domain rules and business data remain in plugins.

Check an explicit prefix such as `#example` with:

```bash
yushuos parse --text "#example hello"
```

Unregistered natural-language requests are handed back to the host. Ambiguous or unavailable routes require clarification; Core does not guess a provider.

## Inspect and invoke

```bash
yushuos doctor
yushuos catalog
```

`doctor` reports configuration and manifest problems. `catalog` lists installed versions, declared capabilities, route availability, and execution status. A declaration alone does not prove that an external account or capability is usable.

After installing the example plugin, send one JSON object on stdin. `invoke` defaults to preview and read-only host mode:

```bash
printf '%s' '{"request_id":"demo-read-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos invoke
```

The output is one JSON result with `status`, `request_id`, and data or a structured error. Use `yushuos status --request-id <id>` to read a receipt. Keep the original request ID when checking an operation.

## Workflows and writes

`plan` always produces a preview. `workflow` executes only when the request asks for execution, host mode is `execute`, and every Core and plugin gate passes. Preview first and inspect expected changes.

External writes require a declared capability and intent, verified and authorized plugin metadata, a matching permission grant, a configured shared operation ledger, an explicit user request, and host execution authorization. Missing gates fail closed. A Core grant does not replace host authorization.

If a write result is `unknown`, query `status` with the original request ID and reconcile remote state. Never replay it with a new ID or blindly retry it. Resume uses recorded receipts and resource references; workflow checkpoints exclude private request bodies.

## Configuration and release commands

Core home defaults to `~/.yushuos`; use `YUSHUOS_HOME` or the global `--config-root` option for another directory. Keep secrets, account bindings, remote resource IDs, and plugin business data out of the source repository. Defaults are preview mode and no permission grants.

Project configuration can select a plugin version, provider, resource scope, or namespaced plugin settings. It cannot expand global permissions or change Core execution mode. Start from `templates/project.yaml.template`.

- `deploy --preview --version <id>`: install an immutable candidate.
- `verify --version <id>`: check package hashes.
- `activate --version <id>`: change the active pointer.
- `rollback`: return to the previous verified version.
- `status --request-id <id>` / `status --plan-id <id>`: inspect receipts or workflow state.
- `resume --file <json>`: resume from receipts; unknown external writes are not replayed.

Run `yushuos <command> --help` for current flags.
