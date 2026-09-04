# Security policy

Clausula is a local-first 0.x system. Its daemon authentication and confirmation model protect local integration calls; they are not a remote internet-service security contract.

## Local daemon boundary

- `clausula-daemon` binds its HTTP projection to loopback by default and owns the writable Store for one `CLAUSULA_HOME`.
- Capability invocation requires a daemon-issued Bearer token whose principal/profile is resolved server-side.
- `X-Clausula-Permissions` and `X-Clausula-Confirmed` do **not** grant authority. Legacy/self-declared permission or confirmation headers are ignored for authorization.
- Confirmation-required writes use a short-lived, one-time server-issued challenge bound to the authenticated principal, capability and canonical argument hash. Replayed, expired, cross-principal or argument-modified challenges fail closed.
- Anonymous workspace projection is intentionally read-only. Capability descriptions may be discoverable locally without granting invocation authority.
- `daemon-auth.json` contains ephemeral local bearer credentials. It is runtime state, not canonical state, and must be protected like a credential file and never committed or shared.

## MCP and plugin boundary

- MCP invocation identity/profile is bound when the host/session adapter is constructed; an invocation cannot submit a different profile or actor identity to elevate itself.
- MCP and plugin-facing APIs cannot self-assert confirmation for a protected write.
- Plugin permissions are fixed by the plugin manifest.
- Plugin package discovery reads entry-point metadata without importing third-party code; explicit manifest loading is the first import/trust transition.
- Host-policy preflight checks declared network hosts, filesystem scopes, secrets, permissions and side effects. This is an authorization contract only. It does **not** constitute process isolation, a network sandbox or filesystem enforcement.
- Real subprocess isolation, timeout/crash containment and OS enforcement remain release-blocking local acceptance work under #23.

## Deployment boundary

- Do not expose the loopback daemon directly to an untrusted network.
- Remote exposure requires a separate authenticated gateway/TLS/deployment contract; local bearer credentials alone are not a multi-tenant internet boundary.
- Do not expose or commit a Clausula data directory, SQLite database, backup bundle, raw artifact store, `.env`, `daemon-auth.json`, private research corpus, agent state or local tool configuration.
- Backup bundles provide integrity checking but are not encrypted by Clausula 0.x. Protect them at rest with operating-system or storage-layer controls.
- Real market/provider credentials must be supplied through local secret handling and must not be embedded in plugin manifests or repository fixtures.

## Reporting

Do not publish credentials, private financial data, private research material or exploit details in a public issue. Use the maintainer contact path exposed on the GitHub profile for sensitive reports. Non-sensitive hardening proposals and reproducible bugs may use GitHub Issues.

## Supported versions

Only the current `main` branch is under active development until the first tagged stable release. The release gate is documented in `docs/project/LOCAL_ACCEPTANCE.md`.
