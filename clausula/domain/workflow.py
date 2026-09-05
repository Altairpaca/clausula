from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .common import DomainValidationError, canonical_timestamp, require_uuid


_ALLOWED_RUN_STATUS = {"planned", "running", "completed", "failed", "cancelled"}
_ALLOWED_ARTIFACT_KIND = {"analysis", "snapshot", "report", "decision-input", "diagnostic"}


def _text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise DomainValidationError(f"{field} cannot be empty")
    return normalized


def _sha256(value: str, field: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise DomainValidationError(f"{field} must be a SHA-256 hex digest")
    return normalized


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(canonical_timestamp(value))


def assert_point_in_time(*, effective_at: str, known_at: str, as_of: str) -> None:
    """Reject hindsight: facts must be known no later than the workflow cut-off."""

    effective = _utc(effective_at)
    known = _utc(known_at)
    cutoff = _utc(as_of)
    if effective > known:
        raise DomainValidationError("effective_at cannot be after known_at")
    if known > cutoff:
        raise DomainValidationError("known_at cannot be after workflow as_of")


@dataclass(frozen=True, slots=True)
class InvestmentWorkflow:
    id: str
    name: str
    objective: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "workflow id"))
        object.__setattr__(self, "name", _text(self.name, "workflow name"))
        object.__setattr__(self, "objective", _text(self.objective, "workflow objective"))
        object.__setattr__(self, "created_at", canonical_timestamp(self.created_at))
        object.__setattr__(self, "source_artifact_id", require_uuid(self.source_artifact_id, "source_artifact_id"))
        object.__setattr__(self, "import_batch_id", require_uuid(self.import_batch_id, "import_batch_id"))


@dataclass(frozen=True, slots=True)
class WorkflowInputRef:
    kind: str
    object_id: str
    effective_at: str
    known_at: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "input kind"))
        object.__setattr__(self, "object_id", require_uuid(self.object_id, "input object_id"))
        object.__setattr__(self, "effective_at", canonical_timestamp(self.effective_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "input sha256"))


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: str
    workflow_id: str
    as_of: str
    started_at: str
    status: str
    inputs: tuple[WorkflowInputRef, ...]
    completed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "workflow run id"))
        object.__setattr__(self, "workflow_id", require_uuid(self.workflow_id, "workflow_id"))
        object.__setattr__(self, "as_of", canonical_timestamp(self.as_of))
        object.__setattr__(self, "started_at", canonical_timestamp(self.started_at))
        status = _text(self.status, "workflow run status").lower()
        if status not in _ALLOWED_RUN_STATUS:
            raise DomainValidationError("workflow run status is invalid")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if not self.inputs:
            raise DomainValidationError("workflow run requires at least one input")
        seen: set[tuple[str, str]] = set()
        for item in self.inputs:
            key = (item.kind, item.object_id)
            if key in seen:
                raise DomainValidationError("workflow inputs must be unique by kind and object_id")
            seen.add(key)
            assert_point_in_time(effective_at=item.effective_at, known_at=item.known_at, as_of=self.as_of)
        if self.completed_at is not None:
            completed = canonical_timestamp(self.completed_at)
            if _utc(completed) < _utc(self.started_at):
                raise DomainValidationError("completed_at cannot precede started_at")
            object.__setattr__(self, "completed_at", completed)
        if status == "completed" and self.completed_at is None:
            raise DomainValidationError("completed workflow runs require completed_at")
        if status in {"planned", "running"} and self.completed_at is not None:
            raise DomainValidationError("planned/running workflow runs cannot have completed_at")


@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    id: str
    run_id: str
    kind: str
    uri: str
    sha256: str
    generated_at: str
    input_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "workflow artifact id"))
        object.__setattr__(self, "run_id", require_uuid(self.run_id, "run_id"))
        kind = _text(self.kind, "artifact kind").lower()
        if kind not in _ALLOWED_ARTIFACT_KIND:
            raise DomainValidationError("workflow artifact kind is invalid")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "uri", _text(self.uri, "artifact uri"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "artifact sha256"))
        object.__setattr__(self, "generated_at", canonical_timestamp(self.generated_at))
        hashes = tuple(_sha256(value, "input sha256") for value in self.input_sha256s)
        if not hashes:
            raise DomainValidationError("workflow artifact must record input digests")
        if len(hashes) != len(set(hashes)):
            raise DomainValidationError("workflow artifact input digests must be unique")
        object.__setattr__(self, "input_sha256s", hashes)


def input_digest_set(inputs: Iterable[WorkflowInputRef]) -> frozenset[str]:
    return frozenset(item.sha256 for item in inputs)


def verify_artifact_inputs(run: WorkflowRun, artifact: WorkflowArtifact) -> bool:
    """An artifact may consume a subset of run inputs, but never unrecorded inputs."""

    if artifact.run_id != run.id:
        return False
    return set(artifact.input_sha256s).issubset(input_digest_set(run.inputs))
