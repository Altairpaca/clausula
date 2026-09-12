from __future__ import annotations

import unittest

from clausula.domain.common import DomainValidationError
from clausula.domain.workflow import (
    InvestmentWorkflow,
    WorkflowArtifact,
    WorkflowInputRef,
    WorkflowRun,
    verify_artifact_inputs,
)


UUIDS = {
    "workflow": "11111111-1111-4111-8111-111111111111",
    "run": "22222222-2222-4222-8222-222222222222",
    "source": "33333333-3333-4333-8333-333333333333",
    "batch": "44444444-4444-4444-8444-444444444444",
    "portfolio": "55555555-5555-4555-8555-555555555555",
    "market": "66666666-6666-4666-8666-666666666666",
    "artifact": "77777777-7777-4777-8777-777777777777",
}


def input_ref(kind: str, object_id: str, digest: str, known_at: str = "2026-09-05T09:00:00Z") -> WorkflowInputRef:
    return WorkflowInputRef(
        kind=kind,
        object_id=object_id,
        effective_at="2026-09-05T08:00:00Z",
        known_at=known_at,
        sha256=digest,
    )


class InvestmentWorkflowTests(unittest.TestCase):
    def test_workflow_run_is_point_in_time_and_reproducible(self) -> None:
        workflow = InvestmentWorkflow(
            id=UUIDS["workflow"],
            name="daily risk review",
            objective="Reproduce the evidence available before the rebalance decision.",
            created_at="2026-09-05T07:00:00Z",
            source_artifact_id=UUIDS["source"],
            import_batch_id=UUIDS["batch"],
        )
        self.assertEqual(workflow.name, "daily risk review")

        run = WorkflowRun(
            id=UUIDS["run"],
            workflow_id=workflow.id,
            as_of="2026-09-05T10:00:00Z",
            started_at="2026-09-05T10:01:00Z",
            completed_at="2026-09-05T10:02:00Z",
            status="completed",
            inputs=(
                input_ref("portfolio-snapshot", UUIDS["portfolio"], "a" * 64),
                input_ref("market-snapshot", UUIDS["market"], "b" * 64),
            ),
        )
        artifact = WorkflowArtifact(
            id=UUIDS["artifact"],
            run_id=run.id,
            kind="analysis",
            uri="artifact://risk-review.json",
            sha256="c" * 64,
            generated_at="2026-09-05T10:02:00Z",
            input_sha256s=("a" * 64, "b" * 64),
        )
        self.assertTrue(verify_artifact_inputs(run, artifact))

    def test_rejects_hindsight_inputs(self) -> None:
        with self.assertRaisesRegex(DomainValidationError, "known_at cannot be after workflow as_of"):
            WorkflowRun(
                id=UUIDS["run"],
                workflow_id=UUIDS["workflow"],
                as_of="2026-09-05T10:00:00Z",
                started_at="2026-09-05T10:01:00Z",
                status="running",
                inputs=(input_ref("market-snapshot", UUIDS["market"], "a" * 64, "2026-09-05T10:00:01Z"),),
            )

    def test_completed_run_requires_completion_timestamp(self) -> None:
        with self.assertRaisesRegex(DomainValidationError, "require completed_at"):
            WorkflowRun(
                id=UUIDS["run"],
                workflow_id=UUIDS["workflow"],
                as_of="2026-09-05T10:00:00Z",
                started_at="2026-09-05T10:01:00Z",
                status="completed",
                inputs=(input_ref("market-snapshot", UUIDS["market"], "a" * 64),),
            )

    def test_artifact_cannot_claim_unrecorded_input(self) -> None:
        run = WorkflowRun(
            id=UUIDS["run"],
            workflow_id=UUIDS["workflow"],
            as_of="2026-09-05T10:00:00Z",
            started_at="2026-09-05T10:01:00Z",
            status="running",
            inputs=(input_ref("market-snapshot", UUIDS["market"], "a" * 64),),
        )
        artifact = WorkflowArtifact(
            id=UUIDS["artifact"],
            run_id=run.id,
            kind="report",
            uri="artifact://report.json",
            sha256="c" * 64,
            generated_at="2026-09-05T10:02:00Z",
            input_sha256s=("b" * 64,),
        )
        self.assertFalse(verify_artifact_inputs(run, artifact))


if __name__ == "__main__":
    unittest.main()
