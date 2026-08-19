from datetime import datetime
from decimal import Decimal
import uuid

import pytest

from clausula.domain import (
    DomainValidationError,
    TemporalMetadata,
    TransactionLeg,
    canonical_decimal,
    canonical_timestamp,
    dec,
)


def test_financial_values_reject_binary_float_and_non_finite_values():
    with pytest.raises(DomainValidationError, match="binary floating point"):
        dec(0.1)
    for value in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(DomainValidationError, match="finite"):
            dec(value)


def test_decimal_serialization_is_canonical():
    assert canonical_decimal(Decimal("100.000")) == "100"
    assert canonical_decimal(Decimal("0.0100")) == "0.01"
    assert canonical_decimal(Decimal("-0.00")) == "0"


def test_timestamp_contract_normalizes_to_utc_and_rejects_naive_time():
    assert canonical_timestamp("2025-01-01T08:00:00+08:00") == "2025-01-01T00:00:00.000000+00:00"
    with pytest.raises(DomainValidationError, match="explicit offset"):
        canonical_timestamp(datetime(2025, 1, 1, 8, 0))


def test_known_at_cannot_be_after_recorded_at():
    with pytest.raises(ValueError, match="known_at"):
        TemporalMetadata(
            "2025-01-01",
            "2025-03-01T00:00:00+00:00",
            "2025-02-01T00:00:00+00:00",
        )


def test_internal_identifiers_must_be_uuids():
    with pytest.raises(DomainValidationError, match="UUID"):
        TransactionLeg("broker-account", None, Decimal("0"), Decimal("1"), "USD", "cash")

    account_id = str(uuid.uuid4())
    leg = TransactionLeg(account_id, None, Decimal("0"), Decimal("1.00"), "usd", "cash")
    assert leg.account_id == account_id
    assert leg.currency == "USD"
