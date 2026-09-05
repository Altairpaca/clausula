# Investment workflow foundation

Clausula workflows bind portfolio, market and thesis/research inputs to an explicit information-time cut-off and immutable content digests, then produce reproducible analysis artifacts without granting opaque model output transaction authority.

`WorkflowRun` enforces `effective_at <= known_at <= as_of`. `workflow_fingerprint()` excludes run UUID and wall-clock execution time so identical workflow/evidence state yields identical input identity. Artifacts may consume only recorded input digests and must be generated inside the run execution window.

AI components may produce candidate analysis, summaries or reports, but inherit the same provenance rules and remain downstream of existing policy/decision boundaries.
