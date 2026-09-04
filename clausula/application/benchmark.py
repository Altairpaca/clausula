from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from clausula.domain import canonical_decimal, dec

from .portfolio import PortfolioService
from .ports import CoreRepository


class ReturnSeriesRepository(Protocol):
    def return_series(
        self,
        dataset_name: str,
        dataset_version: str,
        identifier: str,
        *,
        identifier_scheme: str = "ticker",
        as_of: str,
        known_as_of: str,
    ) -> dict[str, Any]: ...


class BenchmarkService:
    """Compare ledger-derived portfolio TWR with an explicitly semantic benchmark."""

    def __init__(
        self,
        repository: CoreRepository,
        return_repository: ReturnSeriesRepository,
    ) -> None:
        self.repository = repository
        self.returns = return_repository
        self.portfolios = PortfolioService(repository)

    def compare(
        self,
        portfolio_id: str,
        *,
        benchmark_dataset_name: str,
        benchmark_dataset_version: str,
        benchmark_identifier: str,
        as_of: str,
        known_as_of: str,
        benchmark_identifier_scheme: str = "ticker",
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        benchmark = self.returns.return_series(
            benchmark_dataset_name,
            benchmark_dataset_version,
            benchmark_identifier,
            identifier_scheme=benchmark_identifier_scheme,
            as_of=as_of,
            known_as_of=known_as_of,
        )
        if benchmark["status"] != "available" or len(benchmark["series"]) < 2:
            return {
                "status": "unavailable",
                "portfolio_id": portfolio_id,
                "benchmark": benchmark,
                "reason": "benchmark comparison requires at least two explicit return-index observations",
            }

        dates = [row["observed_at"] for row in benchmark["series"]]
        portfolio = self.portfolios.performance(
            portfolio_id,
            dates,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        portfolio_return = dec(portfolio["time_weighted_return"])
        benchmark_return = dec(benchmark["cumulative_return"])
        relative = (
            None
            if Decimal(1) + benchmark_return == 0
            else (Decimal(1) + portfolio_return)
            / (Decimal(1) + benchmark_return)
            - Decimal(1)
        )
        return {
            "status": "available",
            "portfolio_id": portfolio_id,
            "knowledge_mode": "fixed_vintage",
            "known_as_of": known_as_of,
            "start_date": portfolio["start_date"],
            "end_date": portfolio["end_date"],
            "portfolio_semantics": "ledger_time_weighted_wealth_return",
            "portfolio_return": canonical_decimal(portfolio_return),
            "benchmark": benchmark,
            "benchmark_return": canonical_decimal(benchmark_return),
            "active_return_difference": canonical_decimal(
                portfolio_return - benchmark_return
            ),
            "relative_wealth_return": (
                None if relative is None else canonical_decimal(relative)
            ),
            "comparability": (
                "total_return_comparable_if_ledger_income_is_complete"
                if benchmark["semantics"] == "total_return"
                else "benchmark_is_price_return_only"
            ),
            "portfolio_performance": portfolio,
        }
