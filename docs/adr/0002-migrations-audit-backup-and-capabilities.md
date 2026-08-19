# ADR 0002: Migrations, Audit, Backup, and Capability Contracts

- Status: Accepted; M1 freeze
- Date: 2026-08-19

## Context

Every later domain depends on durable schema evolution, evidence that canonical writes used controlled operations, complete local backup, and one executable contract shared by clients. The initial kernel used an idempotent bootstrap script, database-only backup, and direct CLI service calls.

## Decision

SQLite schema changes are ordered, checksummed, forward-only migrations. `schema_migrations` is append-only. Startup rejects unknown future versions and checksum mismatches. Downgrade is never automatic: restore a compatible backup or run an explicit, separately reviewed export/import migration.

Canonical writes append an audit event in the same database transaction. Events form a SHA-256 chain over sequence, identity, time, actor, operation, object, canonical payload, and previous hash. Startup does not silently repair a broken chain. Restore appends a new local `system.restore` event after validating the source chain.

The audit chain is tamper-evident, not a digital signature. A party with unrestricted database and application-code access can rebuild a chain. Future stronger assurance may anchor signed chain heads outside the database; the current contract must not be described as tamper-proof.

The canonical backup format is a deterministic ZIP layout with an integrity-checked SQLite snapshot, referenced immutable raw artifacts, canonical JSONL export, and a manifest containing every file hash, schema version, and audit head. Restore rejects duplicate or unsafe paths, missing entries, hash mismatch, SQLite corruption, audit mismatch, schema mismatch, and conflicting local raw files before replacing the database.

Backups are not encrypted in M1. They contain sensitive personal financial data and must remain in trusted local storage until an encrypted container and key-management ADR is accepted.

Application services depend on typed repository protocols. The Capability Registry is the canonical client contract and declares name, schemas, mode, determinism, side effect, permission, confirmation, provenance, and implementation version. CLI and Python SDK project this registry; future HTTP and MCP adapters must not add business behavior.

## Consequences

M1 is frozen at schema version 2. New tables or schema changes require a migration and upgrade test. Client contract changes require capability tests. Audit and backup verification are part of `system.check_integrity` and release gates.
