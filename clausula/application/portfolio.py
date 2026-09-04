from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
from typing import Any

from clausula.analytics.performance import performance_summary
from clausula.analytics.portfolio import aggregate_accounts, value_portfolio
from clausula.domain import (
    Portfolio,
    PortfolioMembershipEvent,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)

from .ledger import LedgerService
from .ports import CoreRepository


PORTFOLIO_EVENT_FORMAT = "clausula-portfolio-event-v1"


@dataclass(slots=True)
class _ValuationReadCache:
    """Per-snapshot cache; never reused across temporal or dataset cutoffs."""

    instruments: dict[str, dict[str, Any]] = field(default_factory=dict)
    prices: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    fx_rates: dict[tuple[str, str], dict[str, Any] | None] = field(default_factory=dict)


class PortfolioService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository
        self.ledger = LedgerService(repository)

    def create(
        self,
        name: str,
        base_currency: str = "USD",
        *,
        created_at: str | None = None,
    ) -> str:
        portfolio_id = new_id()
        created_time = canonical_timestamp(created_at or now())
        normalized_name = name.strip()
        normalized_currency = base_currency.strip().upper()
        if not normalized_name or not normalized_currency:
            raise ValueError("portfolio name and base currency are required")
        provenance = json.dumps(
            {
                "format": PORTFOLIO_EVENT_FORMAT,
                "operation": "portfolio.create",
                "portfolio_id": portfolio_id,
                "name": normalized_name,
                "base_currency": normalized_currency,
                "created_at": created_time,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact(
            "manual://portfolio-create", provenance
        )
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-portfolio",
            adapter_version="1",
            schema_version="1",
        )
        portfolio = Portfolio(
            portfolio_id,
            normalized_name,
            normalized_currency,
            created_time,
            artifact_id,
            batch_id,
        )
        self.repository.add_portfolio(portfolio)
        return portfolio.id

    def set_membership(
        self,
        portfolio_id: str,
        account_id: str,
        action: str,
        effective_at: str,
        *,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> str:
        recorded_time = canonical_timestamp(recorded_at or now())
        event_id = new_id()
        knowledge_time = canonical_timestamp(known_at or recorded_time)
        effective_time = canonical_timestamp(effective_at)
        normalized_action = action.strip().lower()
        if normalized_action not in {"add", "remove"}:
            raise ValueError("membership action must be add or remove")
        if knowledge_time > recorded_time:
            raise ValueError("known_at cannot be after recorded_at")
        self.repository.require_account(account_id)
        current = self.repository.portfolio_accounts(
            portfolio_id, effective_time, knowledge_time
        )
        if (normalized_action == "add") == (account_id in current):
            raise ValueError("portfolio membership event does not change state")
        provenance = json.dumps(
            {
                "format": PORTFOLIO_EVENT_FORMAT,
                "operation": "portfolio.set_membership",
                "membership_event_id": event_id,
                "portfolio_id": portfolio_id,
                "account_id": account_id,
                "action": normalized_action,
                "effective_at": effective_time,
                "known_at": knowledge_time,
                "recorded_at": recorded_time,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact(
            "manual://portfolio-membership", provenance
        )
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-portfolio-membership",
            adapter_version="1",
            schema_version="1",
        )
        event = PortfolioMembershipEvent(
            event_id,
            portfolio_id,
            account_id,
            normalized_action,
            effective_time,
            knowledge_time,
            recorded_time,
            artifact_id,
            batch_id,
        )
        self.repository.add_portfolio_membership(event)
        return event.id

    def accounts(
        self, portfolio_id: str, as_of: str, *, known_as_of: str | None = None
    ) -> list[str]:
        return self.repository.portfolio_accounts(portfolio_id, as_of, known_as_of)

    def valuation(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
        base_currency: str = "USD",
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        return self._valuation(
            account_id,
            as_of,
            known_as_of=known_as_of,
            base_currency=base_currency,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
            cache=_ValuationReadCache(),
        )

    def _valuation(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
        base_currency: str = "USD",
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
        cache: _ValuationReadCache,
    ) -> dict[str, Any]:
        effective_cutoff = canonical_timestamp(as_of or now())
        knowledge_cutoff = canonical_timestamp(known_as_of or effective_cutoff)
        state = self.ledger.state(
            account_id,
            effective_cutoff,
            known_as_of=knowledge_cutoff,
        )
        instruments: dict[str, dict[str, Any]] = {}
        prices: dict[str, dict[str, Any]] = {}
        rates: dict[tuple[str, str], dict[str, Any]] = {}

        for instrument_id in state["positions"]:
            if instrument_id not in cache.instruments:
                cache.instruments[instrument_id] = dict(
                    self.repository.instrument_details(instrument_id)
                )
            instruments[instrument_id] = cache.instruments[instrument_id]

            if instrument_id not in cache.prices:
                price = self.repository.market_price(
                    instrument_id,
                    effective_cutoff,
                    knowledge_cutoff,
                    price_dataset_name,
                    price_dataset_version,
                )
                cache.prices[instrument_id] = None if price is None else dict(price)
            cached_price = cache.prices[instrument_id]
            if cached_price is not None:
                prices[instrument_id] = cached_price

        currencies = set(state["cash_by_currency"])
        currencies.update(instrument["currency"] for instrument in instruments.values())
        normalized_base = base_currency.upper()
        for currency in currencies:
            normalized_currency = currency.upper()
            if normalized_currency == normalized_base:
                continue
            for source, target in (
                (normalized_currency, normalized_base),
                (normalized_base, normalized_currency),
            ):
                key = (source, target)
                if key not in cache.fx_rates:
                    rate = self.repository.market_fx_rate(
                        source,
                        target,
                        effective_cutoff,
                        knowledge_cutoff,
                        fx_dataset_name,
                        fx_dataset_version,
                    )
                    cache.fx_rates[key] = None if rate is None else dict(rate)
                cached_rate = cache.fx_rates[key]
                if cached_rate is not None:
                    rates[key] = cached_rate

        result = value_portfolio(
            state,
            instruments,
            prices,
            rates,
            base_currency=base_currency,
        )
        result["known_as_of"] = knowledge_cutoff
        return result

    def portfolio_valuation(
        self,
        portfolio_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        portfolio = dict(self.repository.portfolio(portfolio_id))
        account_ids = self.repository.portfolio_accounts(
            portfolio_id, as_of, known_as_of
        )
        cache = _ValuationReadCache()
        values = [
            self._valuation(
                account_id,
                as_of,
                known_as_of=known_as_of,
                base_currency=portfolio["base_currency"],
                price_dataset_name=price_dataset_name,
                price_dataset_version=price_dataset_version,
                fx_dataset_name=fx_dataset_name,
                fx_dataset_version=fx_dataset_version,
                cache=cache,
            )
            for account_id in account_ids
        ]
        result = aggregate_accounts(portfolio, values)
        result["as_of"] = canonical_timestamp(as_of)
        result["known_as_of"] = canonical_timestamp(known_as_of or as_of)
        return result

    def performance(
        self,
        portfolio_id: str,
        dates: list[str],
        *,
        known_as_of: str | None = None,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        if len(dates) < 2:
            raise ValueError("performance requires at least two dates")
        canonical_dates = [canonical_timestamp(value) for value in dates]
        if len(set(canonical_dates)) != len(canonical_dates):
            raise ValueError("performance dates must be unique")
        normalized_dates = sorted(canonical_dates)
        fixed_knowledge = canonical_timestamp(known_as_of) if known_as_of else None
        points = []
        valuations = []
        for cutoff in normalized_dates:
            point_knowledge = fixed_knowledge or cutoff
            valuation = self.portfolio_valuation(
                portfolio_id,
                cutoff,
                known_as_of=point_knowledge,
                price_dataset_name=price_dataset_name,
                price_dataset_version=price_dataset_version,
                fx_dataset_name=fx_dataset_name,
                fx_dataset_version=fx_dataset_version,
            )
            day = cutoff[:10]
            flow = sum(
                (
                    dec(
                        self.ledger.external_flows(
                            account_id, cutoff, known_as_of=point_knowledge
                        ).get(day, "0")
                    )
                    for account_id in self.repository.portfolio_accounts(
                        portfolio_id, cutoff, point_knowledge
                    )
                ),
                Decimal(0),
            )
            points.append(
                {
                    "date": day,
                    "value": valuation["partial_value"],
                    "net_external_flow": canonical_decimal(flow),
                    "complete": valuation["complete"],
                }
            )
            valuations.append(valuation)
        return {
            "portfolio_id": portfolio_id,
            "known_as_of": fixed_knowledge,
            "knowledge_mode": "fixed_vintage" if fixed_knowledge else "point_in_time",
            **performance_summary(points),
            "valuations": valuations,
        }
