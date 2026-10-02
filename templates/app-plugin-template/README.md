# YushuOS app-plugin adapter template

`sync-app-plugin` builds this thin adapter around an independently installed IMA or Feishu package. It reads the App's local `catalog` command so the YushuOS capability states match the App's implementation, verification, authorization, and enabled flags; it does not call remote APIs. It pins the YushuOS plugin version to the App release version, and its private `bindings.apps.<plugin-id>.active_pointer` refers to the App's private active pointer. The pointer carries only local paths and release metadata; the App config, credentials, and shared ledger remain outside the portable plugin package.

Core and App must point at the same existing operation ledger for writes. YushuOS applies its own explicit permission grant before the adapter runs, and the App runtime applies its existing account, resource, permission, and idempotency checks again. A mismatch fails closed. Do not add credentials to this package or to a project configuration.
