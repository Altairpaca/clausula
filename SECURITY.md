# Security policy

Clausula is currently a local-first 0.x system. Treat its HTTP and MCP projections as local integration surfaces, not as authenticated remote service boundaries.

## Deployment boundary

- Keep the HTTP server bound to loopback unless a separate authenticated gateway is placed in front of it.
- `X-Clausula-Permissions`, `X-Clausula-Confirmed`, and related request headers are capability-projection inputs; they are not authentication credentials.
- Do not expose a Clausula data directory, SQLite database, backup bundle, raw artifact store, `.env`, agent state, or local tool configuration in a public repository.
- Backup bundles provide integrity checking but are not encrypted by Clausula 0.x. Protect them at rest with operating-system or storage-layer controls.

## Reporting

Do not publish credentials, private financial data, or exploit details in a public issue. Use the maintainer contact path exposed on the GitHub profile for sensitive reports. Non-sensitive hardening proposals and reproducible bugs may use GitHub Issues.

## Supported versions

Only the current `main` branch is under active development until the first tagged stable release.
