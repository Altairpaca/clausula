from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from clausula.analytics.performance import performance_summary
from clausula.analytics.portfolio import aggregate_accounts, value_portfolio
from clausula.domain import canonical_decimal, canonical_timestamp, dec, now

from .ledger_fast import LedgerService
from .portfolio import PortfolioService as _BasePortfolioService


class PortfolioService(_BasePortfolioService):
    """Portfolio reads that batch ledger and market inputs by snapshot."""

    def __init__(self, repository):
        super().__init__(repository)
        self.ledger = LedgerService(repository)

    def _market_inputs(
        self,
        states: Iterable[Mapping[str, Any]],
        *,
        as_of: str,
        known_as_of: str,
        base_currency: str,
        price_dataset_name: str | None,
        price_dataset_version: str | None,
        fx_dataset_name: str | None,
        fx_dataset_version: str | None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[tuple[str, str], dict[str, Any]],
    ]:
        materialized = list(states)
        instrument_ids = sorted(
            {
                instrument_id
                for state in materialized
                for instrument_id in state.get("positions", {})
            }
        )
        instrument_batch = getattr(self.repository, "instrument_details_many", None)
        if instrument_batch is not None:
            instruments = {
                key: dict(value)
                for key, value in instrument_batch(instrument_ids).items()
            }
        else:
            instruments = {
                instrument_id: dict(
                    self.repository.instrument_details(instrument_id)
                )
                for instrument_id in instrument_ids
            }

        price_batch = getattr(self.repository, "market_prices_many", None)
        if price_batch is not None:
            prices = {
                key: dict(value)
                for key, value in price_batch(
                    instrument_ids,
                    as_of,
                    known_as_of,
                    price_dataset_name,
                    price_dataset_version,
                ).items()
            }
        else:
            prices = {}
            for instrument_id in instrument_ids:
                price = self.repository.market_price(
                    instrument_id,
                    as_of,
                    known_as_of,
                    price_dataset_name,
                    price_dataset_version,
                )
                if price is not None:
                    prices[instrument_id] = dict(price)

        normalized_base = base_currency.upper()
        currencies = {
            currency.upper()
            for state in materialized
            for currency in state.get("cash_by_currency", {})
        }
        currencies.update(
            str(instrument["currency"]).upper()
            for instrument in instruments.values()
        )
        pairs = sorted(
            {
                pair
                for currency in currencies
                if currency != normalized_base
                for pair in (
                    (currency, normalized_base),
                    (normalized_base, currency),
                )
            }
        )
        fx_batch = getattr(self.repository, "market_fx_rates_many", None)
        if fx_batch is not None:
            rates = {
                key: dict(value)
                for key, value in fx_batch(
                    pairs,
                    as_of,
                    known_as_of,
                    fx_dataset_name,
                    fx_dataset_version,
                ).items()
            }
        else:
            rates = {}
            for source, target in pairs:
                rate = self.repository.market_fx_rate(
                    source,
                    target,
                    as_of,
                    known_as_of,
                    fx_dataset_name,
                    fx_dataset_version,
                )
                if rate is not None:
                    rates[(source, target)] = dict(rate)
        return instruments, prices, rates

    def _value_states(
        self,
        states: list[Mapping[str, Any]],
        *,
        as_of: str,
        known_as_of: str,
        base_currency: str,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> list[dict[str, Any]]:
        instruments, prices, rates = self._market_inputs(
            states,
            as_of=as_of,
            known_as_of=known_as_of,
            base_currency=base_currency,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        values = []
        for state in states:
            value = value_portfolio(
                state,
                instruments,
                prices,
                rates,
                base_currency=base_currency,
            )
            value["known_as_of"] = known_as_of
            values.append(value)
        return values

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
        effective_cutoff = canonical_timestamp(as_of or now())
        knowledge_cutoff = canonical_timestamp(known_as_of or effective_cutoff)
        state = self.ledger.state(
            account_id,
            effective_cutoff,
            known_as_of=knowledge_cutoff,
        )
        return self._value_states(
            [state],
            as_of=effective_cutoff,
            known_as_of=knowledge_cutoff,
            base_currency=base_currency,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )[0]

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
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        portfolio = dict(self.repository.portfolio(portfolio_id))
        account_ids = self.repository.portfolio_accounts(
            portfolio_id, effective_cutoff, knowledge_cutoff
        )
        states = [
            self.ledger.state(
                account_id,
                effective_cutoff,
                known_as_of=knowledge_cutoff,
            )
            for account_id in account_ids
        ]
        values = self._value_states(
            states,
            as_of=effective_cutoff,
            known_as_of=knowledge_cutoff,
            base_currency=portfolio["base_currency"],
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        result = aggregate_accounts(portfolio, values)
        result["as_of"] = effective_cutoff
        result["known_as_of"] = knowledge_cutoff
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
        portfolio = dict(self.repository.portfolio(portfolio_id))

        memberships: dict[str, list[str]] = {}
        all_accounts: set[str] = set()
        for cutoff in normalized_dates:
            point_knowledge = fixed_knowledge or cutoff
            account_ids = self.repository.portfolio_accounts(
                portfolio_id, cutoff, point_knowledge
            )
            memberships[cutoff] = account_ids
            all_accounts.update(account_ids)

        state_maps = {
            account_id: self.ledger.states(
                account_id,
                normalized_dates,
                known_as_of=fixed_knowledge,
            )
            for account_id in sorted(all_accounts)
        }
        flow_maps = {
            account_id: self.ledger.external_flows_for_cutoffs(
                account_id,
                normalized_dates,
                known_as_of=fixed_knowledge,
            )
            for account_id in sorted(all_accounts)
        }

        points: list[dict[str, Any]] = []
        valuations: list[dict[str, Any]] = []
        for cutoff in normalized_dates:
            point_knowledge = fixed_knowledge or cutoff
            states = [
                state_maps[account_id][cutoff]
                for account_id in memberships[cutoff]
            ]
            values = self._value_states(
                states,
                as_of=cutoff,
                known_as_of=point_knowledge,
                base_currency=portfolio["base_currency"],
                price_dataset_name=price_dataset_name,
                price_dataset_version=price_dataset_version,
                fx_dataset_name=fx_dataset_name,
                fx_dataset_version=fx_dataset_version,
            )
            valuation = aggregate_accounts(portfolio, values)
            valuation["as_of"] = cutoff
            valuation["known_as_of"] = point_knowledge
            flow = sum(
                (
                    dec(flow_maps[account_id][cutoff])
                    for account_id in memberships[cutoff]
                ),
                Decimal(0),
            )
            points.append(
                {
                    "date": cutoff[:10],
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
