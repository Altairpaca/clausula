from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from clausula.domain import canonical_timestamp


ACCEPTANCE_EVIDENCE_FORMAT = "clausula-local-acceptance/v1"
ACCEPTANCE_SET_FORMAT = "clausula-local-acceptance-set/v1"
_ALLOWED_CHECK_STATUS = {"pass", "fail", "skip"}


class AcceptanceEvidenceError(ValueError):
    """A derived local-acceptance document violates its evidence contract."""


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise AcceptanceEvidenceError(f"{field} cannot be empty")
    return result


def _hex_digest(value: Any, field: str, *, lengths: tuple[int, ...] = (64,)) -> str:
    result = str(value).strip().lower()
    if len(result) not in lengths or any(char not in "0123456789abcdef" for char in result):
        expected = " or ".join(str(length) for length in lengths)
        raise AcceptanceEvidenceError(f"{field} must be a {expected}-character hexadecimal digest")
    return result


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise AcceptanceEvidenceError(
            f"acceptance evidence must be deterministically JSON serializable: {exc}"
        ) from exc


def _digest_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_environment(environment: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in environment.items():
        normalized[_text(key, "environment key")] = _text(value, f"environment[{key!s}]")
    return dict(sorted(normalized.items()))


def _normalize_resources(
    resources: Sequence[Mapping[str, Any]], *, field: str
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for index, resource in enumerate(resources, 1):
        name = _text(resource.get("name"), f"{field}[{index}].name")
        if name in seen_names:
            raise AcceptanceEvidenceError(f"{field} resource names must be unique: {name}")
        seen_names.add(name)
        normalized.append(
            {
                "name": name,
                "sha256": _hex_digest(
                    resource.get("sha256"), f"{field}[{index}].sha256"
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["name"])


def _normalize_checks(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not checks:
        raise AcceptanceEvidenceError("acceptance evidence requires at least one check")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, check in enumerate(checks, 1):
        check_id = _text(check.get("id"), f"checks[{index}].id")
        if check_id in seen_ids:
            raise AcceptanceEvidenceError(f"check ids must be unique: {check_id}")
        seen_ids.add(check_id)
        status = _text(check.get("status"), f"checks[{index}].status").lower()
        if status not in _ALLOWED_CHECK_STATUS:
            raise AcceptanceEvidenceError(
                f"checks[{index}].status must be pass, fail, or skip"
            )
        item: dict[str, Any] = {
            "id": check_id,
            "status": status,
            "summary": _text(check.get("summary"), f"checks[{index}].summary"),
        }
        if check.get("command") is not None:
            item["command"] = _text(check.get("command"), f"checks[{index}].command")
        diagnostics = tuple(
            _text(value, f"checks[{index}].diagnostics")
            for value in check.get("diagnostics", ())
        )
        if diagnostics:
            item["diagnostics"] = list(diagnostics)
        normalized.append(item)
    return sorted(normalized, key=lambda item: item["id"])


def build_acceptance_evidence(
    *,
    commit_sha: str,
    gate: str,
    profile: str,
    generated_at: str,
    environment: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
    subject_artifacts: Sequence[Mapping[str, Any]] = (),
    materials: Sequence[Mapping[str, Any]] = (),
    limitations: Sequence[str] = (),
    redactions: Sequence[str] = (),
) -> dict[str, Any]:
    """Build self-digesting, canonical local acceptance evidence.

    Evidence is intentionally detached from canonical financial state. The caller
    supplies time/environment data explicitly so identical inputs serialize to an
    identical digest and reports can be safely attached to release issues.
    """

    normalized_commit = _hex_digest(commit_sha, "commit_sha", lengths=(40, 64))
    predicate: dict[str, Any] = {
        "gate": _text(gate, "gate"),
        "profile": _text(profile, "profile"),
        "generated_at": canonical_timestamp(generated_at),
        "environment": _normalize_environment(environment),
        "checks": _normalize_checks(checks),
        "materials": _normalize_resources(materials, field="materials"),
        "limitations": sorted({_text(value, "limitation") for value in limitations}),
        "redactions": sorted({_text(value, "redaction") for value in redactions}),
    }
    payload = {
        "format": ACCEPTANCE_EVIDENCE_FORMAT,
        "subject": {
            "repository_commit": normalized_commit,
            "artifacts": _normalize_resources(subject_artifacts, field="subject_artifacts"),
        },
        "predicate": predicate,
    }
    return payload | {"digest": {"sha256": _digest_payload(payload)}}


def verify_acceptance_evidence(document: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        if document.get("format") != ACCEPTANCE_EVIDENCE_FORMAT:
            raise AcceptanceEvidenceError("acceptance evidence format is unsupported")
        subject = document.get("subject")
        predicate = document.get("predicate")
        digest = document.get("digest")
        if not isinstance(subject, Mapping):
            raise AcceptanceEvidenceError("subject must be an object")
        if not isinstance(predicate, Mapping):
            raise AcceptanceEvidenceError("predicate must be an object")
        if not isinstance(digest, Mapping):
            raise AcceptanceEvidenceError("digest must be an object")

        rebuilt = build_acceptance_evidence(
            commit_sha=subject.get("repository_commit"),
            subject_artifacts=subject.get("artifacts", ()),
            gate=predicate.get("gate"),
            profile=predicate.get("profile"),
            generated_at=predicate.get("generated_at"),
            environment=predicate.get("environment", {}),
            checks=predicate.get("checks", ()),
            materials=predicate.get("materials", ()),
            limitations=predicate.get("limitations", ()),
            redactions=predicate.get("redactions", ()),
        )
        supplied_digest = _hex_digest(digest.get("sha256"), "digest.sha256")
        if supplied_digest != rebuilt["digest"]["sha256"]:
            errors.append("acceptance evidence digest mismatch")
        if _canonical_json(dict(document)) != _canonical_json(rebuilt):
            errors.append("acceptance evidence is not in canonical normalized form")
    except (AcceptanceEvidenceError, TypeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}


def combine_acceptance_evidence(
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not documents:
        raise AcceptanceEvidenceError("at least one acceptance evidence document is required")

    normalized: list[dict[str, Any]] = []
    commits: set[str] = set()
    seen_digests: set[str] = set()
    for index, document in enumerate(documents, 1):
        verification = verify_acceptance_evidence(document)
        if not verification["valid"]:
            raise AcceptanceEvidenceError(
                f"acceptance evidence {index} is invalid: "
                + "; ".join(verification["errors"])
            )
        value = deepcopy(dict(document))
        commit = str(value["subject"]["repository_commit"])
        digest = str(value["digest"]["sha256"])
        commits.add(commit)
        if digest in seen_digests:
            continue
        seen_digests.add(digest)
        normalized.append(value)

    if len(commits) != 1:
        raise AcceptanceEvidenceError(
            "acceptance evidence subjects refer to conflicting repository commits"
        )

    report_refs = sorted(
        (
            {
                "digest": {"sha256": value["digest"]["sha256"]},
                "gate": value["predicate"]["gate"],
                "profile": value["predicate"]["profile"],
            }
            for value in normalized
        ),
        key=lambda item: (item["gate"], item["profile"], item["digest"]["sha256"]),
    )
    payload = {
        "format": ACCEPTANCE_SET_FORMAT,
        "subject": {"repository_commit": next(iter(commits))},
        "reports": report_refs,
    }
    return payload | {"digest": {"sha256": _digest_payload(payload)}}


def verify_acceptance_set(document: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        if document.get("format") != ACCEPTANCE_SET_FORMAT:
            raise AcceptanceEvidenceError("acceptance set format is unsupported")
        subject = document.get("subject")
        reports = document.get("reports")
        digest = document.get("digest")
        if not isinstance(subject, Mapping):
            raise AcceptanceEvidenceError("acceptance set subject must be an object")
        commit = _hex_digest(
            subject.get("repository_commit"), "subject.repository_commit", lengths=(40, 64)
        )
        if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)) or not reports:
            raise AcceptanceEvidenceError("acceptance set requires report references")
        normalized_refs: list[dict[str, Any]] = []
        for index, item in enumerate(reports, 1):
            if not isinstance(item, Mapping):
                raise AcceptanceEvidenceError(f"reports[{index}] must be an object")
            report_digest = item.get("digest")
            if not isinstance(report_digest, Mapping):
                raise AcceptanceEvidenceError(f"reports[{index}].digest must be an object")
            normalized_refs.append(
                {
                    "digest": {
                        "sha256": _hex_digest(
                            report_digest.get("sha256"), f"reports[{index}].digest.sha256"
                        )
                    },
                    "gate": _text(item.get("gate"), f"reports[{index}].gate"),
                    "profile": _text(item.get("profile"), f"reports[{index}].profile"),
                }
            )
        normalized_refs = sorted(
            normalized_refs,
            key=lambda item: (item["gate"], item["profile"], item["digest"]["sha256"]),
        )
        payload = {
            "format": ACCEPTANCE_SET_FORMAT,
            "subject": {"repository_commit": commit},
            "reports": normalized_refs,
        }
        if not isinstance(digest, Mapping):
            raise AcceptanceEvidenceError("acceptance set digest must be an object")
        supplied = _hex_digest(digest.get("sha256"), "digest.sha256")
        expected = _digest_payload(payload)
        if supplied != expected:
            errors.append("acceptance set digest mismatch")
        rebuilt = payload | {"digest": {"sha256": expected}}
        if _canonical_json(dict(document)) != _canonical_json(rebuilt):
            errors.append("acceptance set is not in canonical normalized form")
    except (AcceptanceEvidenceError, TypeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}
