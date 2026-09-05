# Investment workflow foundation

## Objective

Turn reliable accounting and market-data primitives into reproducible research workflows without allowing opaque model output to bypass evidence and decision boundaries.

## Workflow objects

```text
portfolio / market / thesis inputs
        + effective_at
        + known_at
        + sha256 provenance
             ↓
      WorkflowRun(as_of)
             ↓
 deterministic input fingerprint
             ↓
 analysis / report / decision-input artifact
```

The workflow fingerprint excludes run UUID and execution wall-clock timestamps. Two later reproductions with the same workflow ID, information cut-off and exact evidence inputs therefore produce the same content identity even if they execute at different times.

## Evidence rules

- `effective_at <= known_at <= as_of`: no hindsight;
- every input and artifact is content-addressed with SHA-256;
- an artifact may use a subset of run inputs but may not introduce an unrecorded digest;
- artifacts must be generated after run start and, for completed runs, no later than `completed_at`;
- input ordering does not change the reproducibility fingerprint;
- changing an input digest changes the fingerprint.

## Initial workflow candidates

- portfolio review;
- event-driven security analysis;
- factor research artifact generation;
- investment thesis tracking;
- evidence packages consumed by later decision/policy layers.

## AI boundary

Optional AI components may produce artifacts, summaries or candidate analysis, but they inherit the same input/provenance contract. Model output does not acquire transaction authority simply by being attached to a workflow. Trade decisions remain governed by the existing decision/policy/execution layers.
