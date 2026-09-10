from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Any

from clausula.domain import canonical_decimal, canonical_timestamp, dec, now

from .market import RETURN_SEMANTICS

if TYPE_CHECKING:
    from .market_provider import ProviderSnapshot


@dataclass(frozen=True, slots=True)
class ProviderContractIssue:
    code: str
    message: str
    observation_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.observation_index is not None:
            result["observation_index"] = self.observation_index
        return result


@dataclass(frozen=True, slots=True)
class ProviderContractReport:
    provider: str
    dataset_name: str
    version: str
    recorded_at: str
    observation_count: int
    raw_payload_sha256: str | None
    errors: tuple[ProviderContractIssue, ...]
    warnings: tuple[ProviderContractIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "provider": self.provider,
            "dataset_name": self.dataset_name,
            "version": self.version,
            "recorded_at": self.recorded_at,
            "observation_count": self.observation_count,
            "raw_payload_sha256": self.raw_payload_sha256,
            "errors": [issue.as_dict() for issue in self.errors],
            "warnings": [issue.as_dict() for issue in self.warnings],
        }

    def raise_for_errors(self) -> None:
        if not self.errors:
            return
        details = "; ".join(
            f"{issue.code}: {issue.message}"
            + (
                f" [observation {issue.observation_index}]"
                if issue.observation_index is not None
                else ""
            )
            for issue in self.errors
        )
        raise ValueError(f"provider snapshot contract failed: {details}")


def _text(value: Any) -> str:
    return str(value).strip()


def inspect_provider_snapshot(
    snapshot: ProviderSnapshot,
    *,
    recorded_at: str | None = None,
) -> ProviderContractReport:
    """Validate a provider snapshot without touching canonical repository state.

    This preflight is intentionally repository-free so live-provider acceptance can
    produce evidence before an invalid or malformed response creates artifacts,
    imports, instruments, or market rows.
    """

    cutoff = canonical_timestamp(recorded_at or now())
    errors: list[ProviderContractIssue] = []
    warnings: list[ProviderContractIssue] = []

    provider = _text(snapshot.provider)
    dataset_name = _text(snapshot.dataset_name)
    version = _text(snapshot.version)
    for field, value in (
        ("provider", provider),
        ("dataset_name", dataset_name),
        ("version", version),
        ("adapter_name", _text(snapshot.adapter_name)),
        ("adapter_version", _text(snapshot.adapter_version)),
        ("schema_version", _text(snapshot.schema_version)),
    ):
        if not value:
            errors.append(ProviderContractIssue(f"empty_{field}", f"{field} cannot be empty"))

    observations = tuple(snapshot.observations)
    if not observations:
        errors.append(
            ProviderContractIssue(
                "empty_observations", "provider snapshot requires at least one observation"
            )
        )

    raw_payload_sha256: str | None = None
    try:
        raw_mapping = dict(snapshot.raw_payload)
        raw_json = json.dumps(
            raw_mapping,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        raw_payload_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        if not raw_mapping:
            warnings.append(
                ProviderContractIssue(
                    "empty_raw_payload",
                    "raw payload is empty; live acceptance should retain provider evidence",
                )
            )
    except (TypeError, ValueError) as exc:
        errors.append(
            ProviderContractIssue(
                "raw_payload_unserializable",
                f"raw payload must be deterministically JSON serializable: {exc}",
            )
        )

    seen: set[tuple[str, str, str]] = set()
    for index, observation in enumerate(observations, 1):
        identifier = _text(observation.identifier)
        scheme = _text(observation.identifier_scheme)
        currency = _text(observation.currency)
        asset_type = _text(observation.asset_type)
        quality = _text(observation.quality).lower()

        if not identifier:
            errors.append(
                ProviderContractIssue("empty_identifier", "identifier cannot be empty", index)
            )
        if not scheme:
            errors.append(
                ProviderContractIssue(
                    "empty_identifier_scheme", "identifier_scheme cannot be empty", index
                )
            )
        if not currency:
            errors.append(
                ProviderContractIssue("empty_currency", "currency cannot be empty", index)
            )
        if not asset_type:
            errors.append(
                ProviderContractIssue("empty_asset_type", "asset_type cannot be empty", index)
            )
        if quality not in {"accepted", "suspect", "rejected"}:
            errors.append(
                ProviderContractIssue(
                    "invalid_quality",
                    "quality must be accepted, suspect, or rejected",
                    index,
                )
            )

        observed: str | None = None
        knowledge: str | None = None
        try:
            observed = canonical_timestamp(observation.observed_at)
        except ValueError as exc:
            errors.append(
                ProviderContractIssue(
                    "invalid_observed_at", f"invalid observed_at: {exc}", index
                )
            )
        try:
            knowledge = canonical_timestamp(observation.known_at)
        except ValueError as exc:
            errors.append(
                ProviderContractIssue("invalid_known_at", f"invalid known_at: {exc}", index)
            )

        if observed is not None and knowledge is not None:
            if knowledge < observed:
                errors.append(
                    ProviderContractIssue(
                        "known_before_observed",
                        "market observation cannot be known before it was observed",
                        index,
                    )
                )
            if knowledge > cutoff:
                errors.append(
                    ProviderContractIssue(
                        "known_after_recorded",
                        "known_at cannot be after provider import recorded_at",
                        index,
                    )
                )
            key = (scheme, identifier, observed)
            if key in seen:
                errors.append(
                    ProviderContractIssue(
                        "duplicate_observation",
                        "duplicate identifier/scheme/observed_at observation",
                        index,
                    )
                )
            seen.add(key)

        try:
            close = canonical_decimal(observation.close)
            if dec(close) <= 0:
                raise ValueError("close must be positive")
        except ValueError as exc:
            errors.append(
                ProviderContractIssue("invalid_close", f"invalid close: {exc}", index)
            )

        has_return_index = observation.return_index is not None
        has_return_semantics = observation.return_semantics is not None
        if has_return_index != has_return_semantics:
            errors.append(
                ProviderContractIssue(
                    "incomplete_return_series",
                    "return_index and return_semantics must be provided together",
                    index,
                )
            )
        elif has_return_index and has_return_semantics:
            semantics = _text(observation.return_semantics).lower()
            if semantics not in RETURN_SEMANTICS:
                errors.append(
                    ProviderContractIssue(
                        "invalid_return_semantics",
                        "return_semantics must be price_return or total_return",
                        index,
                    )
                )
            try:
                return_index = canonical_decimal(observation.return_index)
                if dec(return_index) <= 0:
                    raise ValueError("return_index must be positive")
            except ValueError as exc:
                errors.append(
                    ProviderContractIssue(
                        "invalid_return_index", f"invalid return_index: {exc}", index
                    )
                )

    return ProviderContractReport(
        provider=provider,
        dataset_name=dataset_name,
        version=version,
        recorded_at=cutoff,
        observation_count=len(observations),
        raw_payload_sha256=raw_payload_sha256,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
