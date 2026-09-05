from __future__ import annotations

from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.adapters.accounting import AccountingPolicyProjection
from clausula.application.accounting import (
    AccountingPolicyError,
    AccountingService,
    DEFAULT_JURISDICTION_PROFILE,
    JURISDICTION_PROFILES,
)


def _accounting(store: Store) -> AccountingService:
    return AccountingService(AccountingPolicyProjection(store))


def test_jurisdiction_vocabulary_is_cn_hk_us() -> None:
    assert JURISDICTION_PROFILES == ("CN", "HK", "US")
    assert DEFAULT_JURISDICTION_PROFILE == "CN"


def test_create_policy_defaults_to_cn_jurisdiction(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account_id = LedgerService(store).create_account("broker", "main")
    service = _accounting(store)
    created = service.create_policy(
        account_id,
        "2026-01-01",
        known_at="2026-01-01",
        recorded_at="2026-01-01",
    )
    assert created["jurisdiction_profile"] == "CN"


def test_explicit_hk_and_us_jurisdictions_are_accepted(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    service = _accounting(store)
    for jurisdiction in ("HK", "US"):
        account_id = LedgerService(store).create_account("broker", jurisdiction)
        created = service.create_policy(
            account_id,
            "2026-01-01",
            jurisdiction_profile=jurisdiction,
            tax_profile_ref=f"local://tax/{jurisdiction.lower()}-v1",
            known_at="2026-01-01",
            recorded_at="2026-01-01",
        )
        assert created["jurisdiction_profile"] == jurisdiction


def test_unknown_jurisdiction_profile_fails_closed(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account_id = LedgerService(store).create_account("broker", "main")
    service = _accounting(store)
    with pytest.raises(AccountingPolicyError, match="jurisdiction_profile"):
        service.create_policy(
            account_id,
            "2026-01-01",
            jurisdiction_profile="XX",
            known_at="2026-01-01",
            recorded_at="2026-01-01",
        )
    with pytest.raises(AccountingPolicyError, match="jurisdiction_profile"):
        service.create_policy(
            account_id,
            "2026-01-01",
            jurisdiction_profile="HK-brokerage-profile",
            known_at="2026-01-01",
            recorded_at="2026-01-01",
        )
