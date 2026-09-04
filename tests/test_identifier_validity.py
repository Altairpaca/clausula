from __future__ import annotations

from pathlib import Path

import pytest

from clausula import LedgerService, Store

TS = "T00:00:00+00:00"


def _ids(store: Store, scheme: str, value: str) -> list[str]:
    return [
        row["instrument_id"]
        for row in store.db.execute(
            "SELECT instrument_id FROM instrument_identifiers WHERE scheme=? AND identifier=?",
            (scheme, value),
        )
    ]


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "home")


@pytest.fixture()
def ledger(store: Store) -> LedgerService:
    return LedgerService(store)


def test_identifier_registration_requires_existing_instrument(store: Store) -> None:
    from clausula.application.identifiers import IdentifierResolutionError, IdentifierService

    service = IdentifierService(store)
    with pytest.raises(KeyError):
        service.register_identifier(
            "00000000-0000-4000-8000-000000000001",
            "ticker",
            "ABC",
            f"2020-01-01{TS}",
            provenance="manual",
        )


def test_old_ticker_resolves_before_change_and_not_after(
    store: Store, ledger: LedgerService
) -> None:
    from clausula.application.identifiers import IdentifierService

    service = IdentifierService(store)
    newco = ledger.resolve_instrument("NEWCO", scheme="ticker")
    oldco = ledger.resolve_instrument("OLDCO", scheme="ticker")
    service.register_identifier(
        oldco, "ticker", "OLDCO", f"2020-01-01{TS}",
        valid_to=f"2025-06-01{TS}", known_at=f"2020-01-02{TS}", provenance="manual"
    )
    service.register_identifier(
        newco, "ticker", "OLDCO", f"2025-06-01{TS}",
        known_at=f"2025-06-02{TS}", provenance="manual"
    )
    assert service.resolve_identifier("ticker", "OLDCO", f"2025-05-31{TS}") == oldco
    assert (
        service.resolve_identifier(
            "ticker", "OLDCO", f"2025-06-01{TS}", known_as_of=f"2025-06-02{TS}"
        )
        == newco
    )


def test_new_ticker_before_effective_or_known_is_unavailable(store: Store) -> None:
    from clausula.application.identifiers import IdentifierService

    service = IdentifierService(store)
    instrument = LedgerService(store).resolve_instrument("AAA", scheme="ticker")
    service.register_identifier(
        instrument,
        "ticker",
        "AAA",
        f"2025-06-01{TS}",
        valid_to=None,
        known_at=f"2025-07-01{TS}",
        provenance="manual",
    )
    assert service.resolve_identifier("ticker", "AAA", f"2025-06-15{TS}") is None
    assert (
        service.resolve_identifier(
            "ticker", "AAA", f"2025-06-15{TS}", known_as_of=f"2025-06-30{TS}"
        )
        is None
    )
    assert (
        service.resolve_identifier(
            "ticker", "AAA", f"2025-08-01{TS}", known_as_of=f"2025-07-02{TS}"
        )
        == instrument
    )


def test_late_backfill_has_no_hindsight(store: Store) -> None:
    from clausula.application.identifiers import IdentifierService

    service = IdentifierService(store)
    instrument = LedgerService(store).resolve_instrument("BBB", scheme="ticker")
    service.register_identifier(
        instrument,
        "ticker",
        "BBB",
        f"2020-01-01{TS}",
        valid_to=None,
        known_at=f"2026-01-01{TS}",
        provenance="manual",
    )
    assert (
        service.resolve_identifier(
            "ticker", "BBB", f"2021-06-15{TS}", known_as_of=f"2025-12-31{TS}"
        )
        is None
    )
    assert (
        service.resolve_identifier(
            "ticker", "BBB", f"2021-06-15{TS}", known_as_of=f"2026-01-02{TS}"
        )
        == instrument
    )


def test_adjacent_ranges_select_exact_boundary_and_overlap_fails_closed(
    store: Store,
) -> None:
    import sqlite3

    from clausula.application.identifiers import IdentifierService

    service = IdentifierService(store)
    ledger = LedgerService(store)
    first = ledger.resolve_instrument("FIRST", scheme="ticker")
    second = ledger.resolve_instrument("SECOND", scheme="ticker")
    service.register_identifier(
        first, "ticker", "TICK", f"2020-01-01{TS}", valid_to=f"2025-06-01{TS}",
        known_at=f"2020-01-02{TS}", provenance="manual"
    )
    service.register_identifier(
        second, "ticker", "TICK", f"2025-06-01{TS}",
        known_at=f"2025-06-02{TS}", provenance="manual"
    )
    assert (
        service.resolve_identifier(
            "ticker", "TICK", f"2025-06-01{TS}", known_as_of=f"2025-06-02{TS}"
        )
        == second
    )
    with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
        service.register_identifier(
            first, "ticker", "TICK", f"2025-05-01{TS}",
            known_at=f"2025-05-02{TS}", provenance="manual"
        )


def test_duplicate_active_identity_fails_closed_even_for_same_instrument(
    store: Store,
) -> None:
    from clausula.application.identifiers import IdentifierResolutionError, IdentifierService

    service = IdentifierService(store)
    ledger = LedgerService(store)
    instrument = ledger.resolve_instrument("DUP", scheme="ticker")
    db = store.db
    db.execute(
        "DROP TRIGGER identifier_validity_ranges_reject_overlap"
    )
    for row_id, valid_from, valid_to, known in (
        ("d1", f"2020-01-01{TS}", f"2024-06-01{TS}", f"2020-01-02{TS}"),
        ("d2", f"2024-01-01{TS}", None, f"2024-01-02{TS}"),
    ):
        db.execute(
            "INSERT INTO identifier_validity_ranges"
            "(id,instrument_id,scheme,value,valid_from,valid_to,known_at,recorded_at,provenance)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (row_id, instrument, "ticker", "DUP", valid_from, valid_to, known, known, "manual"),
        )
    db.commit()
    with pytest.raises(IdentifierResolutionError):
        service.resolve_identifier("ticker", "DUP", f"2024-03-01{TS}")
    assert service.resolve_identifier("ticker", "DUP", f"2023-07-01{TS}") == instrument


def test_different_schemes_are_independent_namespaces(store: Store) -> None:
    from clausula.application.identifiers import IdentifierService

    service = IdentifierService(store)
    ledger = LedgerService(store)
    by_ticker = ledger.resolve_instrument("ABCD", scheme="ticker")
    by_isin = ledger.resolve_instrument("US1234567890", scheme="isin")
    known = f"2020-01-02{TS}"
    service.register_identifier(
        by_ticker, "ticker", "ABCD", f"2020-01-01{TS}", known_at=known, provenance="manual"
    )
    service.register_identifier(
        by_isin, "isin", "US1234567890", f"2020-01-01{TS}", known_at=known, provenance="manual"
    )
    assert service.resolve_identifier("ticker", "ABCD", f"2024-01-01{TS}") == by_ticker
    assert service.resolve_identifier("isin", "US1234567890", f"2024-01-01{TS}") == by_isin
    assert service.resolve_identifier("ticker", "US1234567890", f"2024-01-01{TS}") is None
