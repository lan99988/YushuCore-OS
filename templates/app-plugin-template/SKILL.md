---
name: app-plugin-adapter
description: YushuOS adapter for one independently versioned IMA or Feishu app_plugins release.
---

# Independent App adapter

YushuOS passes a structured capability request to this adapter. It verifies the separately installed App release and its file hashes, then forwards the same request ID, project reference, execution mode, and host mode to that App's own JSON CLI. It does not copy credentials or business records into the Core package. The App plugin remains responsible for its own account authorization, resource scope, write receipt, and readback.
