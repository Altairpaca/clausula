from __future__ import annotations

import pytest

from clausula import Store
from clausula.application import (
    ProviderPrice,
    ProviderSnapshot,
    ProviderSnapshotImporter,
    inspect_provider_snapshot,
)


def _valid_snapshot(**overrides) -> ProviderSnapshot:
    values = {
        "provider": "fixture-provider",
        "dataset_name": "daily-prices",
        "version": "2026-01-02",
        "observations": (
            ProviderPrice(
                identifier="ABC",
                observed_at="2026-01-02",
                known_at="2026-01-02T12:00:00+00:00",
                close="10.25",
                currency="USD",
                instrument_name="ABC Corp",
                quality="accepted",
                return_index="100",
                return_semantics="price_return",
            ),
        ),
        "raw_payload": {"source_id": "fixture-1", "close": "10.25"},
    }
    values.update(overrides)
    return ProviderSnapshot(**values)


def test_provider_preflight_is_deterministic_and_side_effect_free() -> None:
    snapshot = _valid_snapshot()

    first = inspect_provider_snapshot(
        snapshot, recorded_at="2026-01-03T00:00:00+00:00"
    )
    second = inspect_provider_snapshot(
        snapshot, recorded_at="2026-01-03T00:00:00+00:00"
    )

    assert first.valid is True
    assert first.as_dict() == second.as_dict()
    assert first.observation_count == 1
    assert len(first.raw_payload_sha256 or "") == 64
    assert first.errors == ()
    assert first.warnings == ()


def test_provider_preflight_accumulates_contract_failures() -> None:
    snapshot = ProviderSnapshot(
        provider="fixture-provider",
        dataset_name="daily-prices",
        version="bad",
        observations=(
            ProviderPrice(
                identifier="",
                observed_at="2026-01-03",
                known_at="2026-01-02",
                close="-1",
                quality="mystery",
                return_index="0",
                return_semantics=None,
            ),
        ),
        raw_payload={"source_id": "fixture-bad"},
    )

    report = inspect_provider_snapshot(
        snapshot, recorded_at="2026-01-04T00:00:00+00:00"
    )
    codes = {issue.code for issue in report.errors}

    assert report.valid is False
    assert {
        "empty_identifier",
        "invalid_quality",
        "known_before_observed",
        "invalid_close",
        "incomplete_return_series",
    } <= codes


def test_invalid_provider_snapshot_does_not_persist_partial_state(tmp_path) -> None:
    store = Store(tmp_path / "home")
    before = {
        table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "market_datasets", "market_prices")
    }
    snapshot = _valid_snapshot(
        observations=(
            ProviderPrice(
                identifier="ABC",
                observed_at="2026-01-02",
                known_at="2999-01-01",
                close="10",
                instrument_name="ABC Corp",
            ),
        )
    )

    with pytest.raises(ValueError, match="provider snapshot contract failed"):
        ProviderSnapshotImporter(store).import_snapshot(snapshot)

    after = {
        table: store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "market_datasets", "market_prices")
    }
    assert after == before


def test_unserializable_raw_payload_fails_before_persistence(tmp_path) -> None:
    store = Store(tmp_path / "home")
    snapshot = _valid_snapshot(raw_payload={"bad": object()})
    report = inspect_provider_snapshot(
        snapshot, recorded_at="2026-01-03T00:00:00+00:00"
    )

    assert report.valid is False
    assert {issue.code for issue in report.errors} == {"raw_payload_unserializable"}
    before = store.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    with pytest.raises(ValueError, match="raw_payload_unserializable"):
        ProviderSnapshotImporter(store).import_snapshot(snapshot)
    assert store.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == before


def test_empty_raw_payload_is_visible_as_acceptance_warning() -> None:
    report = inspect_provider_snapshot(
        _valid_snapshot(raw_payload={}),
        recorded_at="2026-01-03T00:00:00+00:00",
    )

    assert report.valid is True
    assert [warning.code for warning in report.warnings] == ["empty_raw_payload"]
