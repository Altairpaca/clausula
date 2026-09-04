from __future__ import annotations

from typing import Any

from clausula.domain import canonical_timestamp, now


class IdentifierResolutionError(ValueError):
    pass


class IdentifierService:
    """Point-in-time resolution of historical instrument identifier ranges."""

    def __init__(self, repository: Any):
        if not hasattr(repository, "register_identifier_range"):
            raise TypeError("identifier service requires a range-capable repository")
        self.repository = repository

    def register_identifier(
        self,
        instrument_id: str,
        scheme: str,
        value: str,
        valid_from: str,
        *,
        valid_to: str | None = None,
        known_at: str | None = None,
        recorded_at: str | None = None,
        provenance: str,
    ) -> str:
        recorded = canonical_timestamp(recorded_at or now())
        known = canonical_timestamp(known_at or recorded)
        return self.repository.register_identifier_range(
            instrument_id=instrument_id,
            scheme=scheme,
            value=value,
            valid_from=canonical_timestamp(valid_from),
            valid_to=None if valid_to is None else canonical_timestamp(valid_to),
            known_at=known,
            recorded_at=recorded,
            provenance=provenance,
        )

    def resolve_identifier(
        self,
        scheme: str,
        value: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
    ) -> str | None:
        effective = canonical_timestamp(as_of)
        knowledge = canonical_timestamp(known_as_of or effective)
        if knowledge > now():
            raise IdentifierResolutionError("known_as_of cannot be in the future")
        try:
            return self.repository.resolve_identifier_at(
                scheme=scheme,
                value=value,
                as_of=effective,
                known_as_of=knowledge,
            )
        except ValueError as exc:
            raise IdentifierResolutionError(str(exc)) from exc
