---
name: example-echo
description: Example YushuOS plugin scaffold. Replace this skill with the domain workflow before enabling the plugin.
---

# Example plugin

This scaffold is a read-only example. The host should send a contract-compliant request to YushuOS Core; the Core invokes this plugin using `json-stdio-v1`. Keep domain rules and plugin-owned data in this package. Do not add writes until the capability declares a narrow intent, permission, verification state, and authorization.
