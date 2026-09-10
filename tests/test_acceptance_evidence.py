from __future__ import annotations

from copy import deepcopy

import pytest

from clausula.acceptance import (
    AcceptanceEvidenceError,
    build_acceptance_evidence,
    combine_acceptance_evidence,
    verify_acceptance_evidence,
    verify_acceptance_set,
)


COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


def _report(*, commit: str = COMMIT, gate: str = "#23", profile: str = "daemon-linux"):
    return build_acceptance_evidence(
        commit_sha=commit,
        gate=gate,
        profile=profile,
        generated_at="2026-09-10T08:00:00+00:00",
        environment={
            "os": "Linux 6.x",
            "python": "3.13.15",
            "sqlite": "3.46.1",
        },
        subject_artifacts=(
            {"name": "canonical-export", "sha256": "1" * 64},
        ),
        materials=(
            {"name": "schema-preflight", "sha256": "2" * 64},
        ),
        checks=(
            {
                "id": "daemon.second-owner-rejected",
                "status": "pass",
                "summary": "A second daemon cannot own the same CLAUSULA_HOME.",
                "command": "clausula-daemon --home <redacted>",
            },
            {
                "id": "plugin.network-denied",
                "status": "skip",
                "summary": "Requires bubblewrap on the target host.",
                "diagnostics": ["bwrap unavailable in this fixture"],
            },
        ),
        limitations=("fixture evidence only",),
        redactions=("absolute home path",),
    )


def test_acceptance_evidence_is_deterministic_and_self_verifying() -> None:
    first = _report()
    second = _report()

    assert first == second
    assert len(first["digest"]["sha256"]) == 64
    assert verify_acceptance_evidence(first) == {"valid": True, "errors": []}
    assert [check["id"] for check in first["predicate"]["checks"]] == sorted(
        check["id"] for check in first["predicate"]["checks"]
    )


def test_acceptance_evidence_detects_tampering() -> None:
    report = _report()
    tampered = deepcopy(report)
    tampered["predicate"]["checks"][0]["status"] = "fail"

    verification = verify_acceptance_evidence(tampered)

    assert verification["valid"] is False
    assert "acceptance evidence digest mismatch" in verification["errors"]


def test_acceptance_evidence_rejects_duplicate_check_ids() -> None:
    with pytest.raises(AcceptanceEvidenceError, match="check ids must be unique"):
        build_acceptance_evidence(
            commit_sha=COMMIT,
            gate="#34",
            profile="provider",
            generated_at="2026-09-10",
            environment={"python": "3.13"},
            checks=(
                {"id": "provider.preflight", "status": "pass", "summary": "ok"},
                {"id": "provider.preflight", "status": "pass", "summary": "again"},
            ),
        )


def test_acceptance_set_combines_same_commit_and_rejects_conflicts() -> None:
    host = _report()
    provider = _report(gate="#34", profile="tencent-cn-hk")

    combined = combine_acceptance_evidence((provider, host, provider))

    assert combined["subject"]["repository_commit"] == COMMIT
    assert len(combined["reports"]) == 2
    assert verify_acceptance_set(combined) == {"valid": True, "errors": []}

    with pytest.raises(AcceptanceEvidenceError, match="conflicting repository commits"):
        combine_acceptance_evidence((host, _report(commit=OTHER_COMMIT)))


def test_acceptance_set_detects_tampering() -> None:
    combined = combine_acceptance_evidence((_report(),))
    tampered = deepcopy(combined)
    tampered["reports"][0]["profile"] = "different-profile"

    verification = verify_acceptance_set(tampered)

    assert verification["valid"] is False
    assert "acceptance set digest mismatch" in verification["errors"]
