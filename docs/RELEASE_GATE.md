# Clausula Release Gate

## Purpose

The release gate defines the minimum evidence required before publishing a stable Clausula release.

## Required Checks

### Deterministic accounting

- schema migrations apply from supported previous versions
- replay and exported state remain consistent
- corporate action invariants pass

### Market data provenance

- source adapter is identified
- raw payload capture and digest are available where applicable
- adjustment semantics are explicit

### Agent boundary

- plugin permissions are declared
- host policy authorization is enforced
- sandbox execution failures close safely

### Reproducibility

A release candidate should provide:

- version identifier
- migration compatibility statement
- test evidence
- known limitations

## Principle

Agents may propose actions. The kernel remains responsible for deterministic state transitions and policy enforcement.
