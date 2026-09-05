# Investment workflow foundation

## Objective

Turn reliable accounting and market data primitives into reproducible research workflows.

## Workflow objects

A future workflow should connect:

```text
portfolio state
    +
market snapshot
    +
thesis record
    +
analysis artifact
    -> reproducible decision context
```

## Constraints

- preserve point-in-time semantics;
- keep source provenance attached;
- separate deterministic calculations from optional AI assistance;
- avoid hidden investment decisions generated from opaque heuristics.

## Initial workflow candidates

- portfolio review;
- event-driven security analysis;
- factor research artifact generation;
- investment thesis tracking.

The workflow layer builds on accounting correctness and provider provenance already established in the core system.
