from __future__ import annotations

import unittest

from clausula.domain.workflow import (
    WorkflowArtifact,
    WorkflowInputRef,
    WorkflowRun,
    verify_artifact_temporal,
    verify_workflow_artifact,
    workflow_fingerprint,
)

RUN_A = "11111111-1111-4111-8111-111111111111"
RUN_B = "22222222-2222-4222-8222-222222222222"
WORKFLOW = "33333333-3333-4333-8333-333333333333"
OBJECT_A = "44444444-4444-4444-8444-444444444444"
OBJECT_B = "55555555-5555-4555-8555-555555555555"
ARTIFACT = "66666666-6666-4666-8666-666666666666"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def input_ref(kind: str, object_id: str, digest: str) -> WorkflowInputRef:
    return WorkflowInputRef(
        kind=kind,
        object_id=object_id,
        effective_at="2026-09-04T00:00:00Z",
        known_at="2026-09-04T01:00:00Z",
        sha256=digest,
    )


def run(run_id: str, inputs: tuple[WorkflowInputRef, ...]) -> WorkflowRun:
    return WorkflowRun(
        id=run_id,
        workflow_id=WORKFLOW,
        as_of="2026-09-04T02:00:00Z",
        started_at="2026-09-05T00:00:00Z",
        completed_at="2026-09-05T00:10:00Z",
        status="completed",
        inputs=inputs,
    )


class WorkflowReproducibilityTests(unittest.TestCase):
    def test_fingerprint_ignores_run_identity_and_input_order(self) -> None:
        first = input_ref("portfolio", OBJECT_A, SHA_A)
        second = input_ref("market", OBJECT_B, SHA_B)
        self.assertEqual(
            workflow_fingerprint(run(RUN_A, (first, second))),
            workflow_fingerprint(run(RUN_B, (second, first))),
        )

    def test_fingerprint_changes_when_evidence_changes(self) -> None:
        first = input_ref("portfolio", OBJECT_A, SHA_A)
        changed = input_ref("portfolio", OBJECT_A, SHA_C)
        self.assertNotEqual(
            workflow_fingerprint(run(RUN_A, (first,))),
            workflow_fingerprint(run(RUN_B, (changed,))),
        )

    def test_artifact_must_live_inside_execution_window(self) -> None:
        workflow_run = run(RUN_A, (input_ref("portfolio", OBJECT_A, SHA_A),))
        before = WorkflowArtifact(
            id=ARTIFACT,
            run_id=RUN_A,
            kind="analysis",
            uri="artifact://before",
            sha256=SHA_C,
            generated_at="2026-09-04T23:59:59Z",
            input_sha256s=(SHA_A,),
        )
        after = WorkflowArtifact(
            id=ARTIFACT,
            run_id=RUN_A,
            kind="analysis",
            uri="artifact://after",
            sha256=SHA_C,
            generated_at="2026-09-05T00:10:01Z",
            input_sha256s=(SHA_A,),
        )
        valid = WorkflowArtifact(
            id=ARTIFACT,
            run_id=RUN_A,
            kind="analysis",
            uri="artifact://valid",
            sha256=SHA_C,
            generated_at="2026-09-05T00:05:00Z",
            input_sha256s=(SHA_A,),
        )
        self.assertFalse(verify_artifact_temporal(workflow_run, before))
        self.assertFalse(verify_artifact_temporal(workflow_run, after))
        self.assertTrue(verify_workflow_artifact(workflow_run, valid))

    def test_artifact_with_unrecorded_input_is_not_reproducible(self) -> None:
        workflow_run = run(RUN_A, (input_ref("portfolio", OBJECT_A, SHA_A),))
        artifact = WorkflowArtifact(
            id=ARTIFACT,
            run_id=RUN_A,
            kind="analysis",
            uri="artifact://invalid-input",
            sha256=SHA_C,
            generated_at="2026-09-05T00:05:00Z",
            input_sha256s=(SHA_B,),
        )
        self.assertFalse(verify_workflow_artifact(workflow_run, artifact))


if __name__ == "__main__":
    unittest.main()
