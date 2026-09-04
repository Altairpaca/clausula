from __future__ import annotations

from clausula.application import PortfolioService


class CountingRepository:
    def __init__(self) -> None:
        self.instrument_reads = 0
        self.price_reads = 0
        self.fx_reads = 0

    def portfolio(self, portfolio_id: str):
        return {"id": portfolio_id, "name": "Household", "base_currency": "USD"}

    def portfolio_accounts(self, portfolio_id: str, as_of: str, known_as_of: str | None = None):
        return ["account-a", "account-b"]

    def transactions(self, account_id: str, as_of: str | None = None, known_as_of: str | None = None):
        return [{"id": f"{account_id}-transaction"}]

    def legs(self, transaction_id: str):
        account_id = transaction_id.removesuffix("-transaction")
        return [
            {
                "account_id": account_id,
                "instrument_id": "shared-instrument",
                "quantity": "1",
                "amount": "0",
                "currency": "EUR",
                "leg_type": "position",
            }
        ]

    def instrument_details(self, instrument_id: str):
        self.instrument_reads += 1
        return {
            "id": instrument_id,
            "scheme": "ticker",
            "identifier": "SHARED",
            "name": "Shared holding",
            "asset_type": "stock",
            "currency": "EUR",
        }

    def market_price(
        self,
        instrument_id: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ):
        self.price_reads += 1
        return {
            "instrument_id": instrument_id,
            "dataset_id": "dataset",
            "observed_at": "2026-09-04T00:00:00+00:00",
            "known_at": "2026-09-04T00:00:00+00:00",
            "close": "100",
            "currency": "EUR",
        }

    def market_fx_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ):
        self.fx_reads += 1
        rate = "1.2" if (from_currency, to_currency) == ("EUR", "USD") else "0.8333333333333333333333333333"
        return {
            "observed_at": "2026-09-04T00:00:00+00:00",
            "known_at": "2026-09-04T00:00:00+00:00",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": rate,
        }


def test_portfolio_valuation_reuses_identical_market_reads_across_accounts() -> None:
    repository = CountingRepository()
    service = PortfolioService(repository)  # type: ignore[arg-type]

    valuation = service.portfolio_valuation(
        "portfolio",
        "2026-09-04",
        known_as_of="2026-09-04",
    )

    assert valuation["complete"] is True
    assert valuation["total_value"] == "240"
    assert len(valuation["accounts"]) == 2
    assert len(valuation["concentration"]) == 1

    # The two accounts hold the same instrument at the same temporal/dataset cutoff.
    # Read cost must therefore follow unique market inputs, not account count.
    assert repository.instrument_reads == 1
    assert repository.price_reads == 1
    assert repository.fx_reads == 2  # one direct and one inverse pair, once each
