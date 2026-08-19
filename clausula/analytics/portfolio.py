from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from clausula.domain import ValuationGap, canonical_decimal, dec


def _fx_factor(
    currency: str,
    base_currency: str,
    rates: Mapping[tuple[str, str], Mapping[str, Any]],
) -> Decimal | None:
    currency = currency.upper()
    base_currency = base_currency.upper()
    if currency == base_currency:
        return Decimal(1)
    direct = rates.get((currency, base_currency))
    if direct is not None:
        return dec(direct["rate"])
    inverse = rates.get((base_currency, currency))
    if inverse is not None:
        rate = dec(inverse["rate"])
        if rate == 0:
            return None
        return Decimal(1) / rate
    return None


def _line_weight(value: Decimal, total: Decimal, complete: bool) -> str | None:
    if not complete or total == 0:
        return None
    return canonical_decimal(value / total)


def value_portfolio(
    state: Mapping[str, Any],
    instruments: Mapping[str, Mapping[str, Any]],
    prices: Mapping[str, Mapping[str, Any]],
    fx_rates: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    base_currency: str,
) -> dict[str, Any]:
    base_currency = base_currency.upper()
    gaps: list[ValuationGap] = []
    position_lines: list[dict[str, Any]] = []
    cash_lines: list[dict[str, Any]] = []
    allocation_values: dict[str, Decimal] = {"cash": Decimal(0)}
    currency_values: dict[str, Decimal] = {}
    total = Decimal(0)

    for currency, raw_amount in sorted(state.get("cash_by_currency", {}).items()):
        amount = dec(raw_amount)
        factor = _fx_factor(currency, base_currency, fx_rates)
        if factor is None:
            gaps.append(ValuationGap("cash_fx", currency, f"missing FX rate to {base_currency}"))
            continue
        base_value = amount * factor
        total += base_value
        currency_values[currency] = currency_values.get(currency, Decimal(0)) + base_value
        allocation_values["cash"] += base_value
        cash_lines.append(
            {
                "currency": currency,
                "amount": canonical_decimal(amount),
                "base_value": canonical_decimal(base_value),
                "fx_factor": canonical_decimal(factor),
            }
        )

    for instrument_id, raw_quantity in sorted(state.get("positions", {}).items()):
        quantity = dec(raw_quantity)
        if quantity < 0:
            gaps.append(
                ValuationGap(
                    "unsupported_short_position",
                    instrument_id,
                    "negative positions are outside the M3 valuation contract",
                )
            )
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None:
            gaps.append(ValuationGap("instrument", instrument_id, "instrument metadata is missing"))
            continue
        price = prices.get(instrument_id)
        if price is None:
            gaps.append(ValuationGap("price", instrument_id, "accepted price is missing"))
            continue
        if price["currency"].upper() != instrument["currency"].upper():
            gaps.append(
                ValuationGap(
                    "price_currency",
                    instrument_id,
                    f"price currency {price['currency']} does not match instrument currency {instrument['currency']}",
                )
            )
            continue
        local_value = quantity * dec(price["close"])
        factor = _fx_factor(instrument["currency"], base_currency, fx_rates)
        if factor is None:
            gaps.append(
                ValuationGap(
                    "position_fx",
                    instrument_id,
                    f"missing FX rate from {instrument['currency']} to {base_currency}",
                )
            )
            continue
        base_value = local_value * factor
        total += base_value
        currency_values[instrument["currency"]] = currency_values.get(
            instrument["currency"], Decimal(0)
        ) + base_value
        asset_type = instrument["asset_type"]
        allocation_values[asset_type] = allocation_values.get(asset_type, Decimal(0)) + base_value
        position_lines.append(
            {
                "instrument_id": instrument_id,
                "identifier": f"{instrument['scheme']}:{instrument['identifier']}",
                "asset_type": asset_type,
                "quantity": canonical_decimal(quantity),
                "price": canonical_decimal(price["close"]),
                "currency": instrument["currency"],
                "local_value": canonical_decimal(local_value),
                "base_value": canonical_decimal(base_value),
                "fx_factor": canonical_decimal(factor),
                "price_observed_at": price["observed_at"],
                "price_dataset_id": price["dataset_id"],
            }
        )

    complete = not gaps
    allocation = [
        {
            "asset_type": asset_type,
            "base_value": canonical_decimal(value),
            "weight": _line_weight(value, total, complete),
        }
        for asset_type, value in sorted(allocation_values.items())
        if value != 0
    ]
    concentration = sorted(
        [
            {
                "instrument_id": line["instrument_id"],
                "identifier": line["identifier"],
                "base_value": line["base_value"],
                "weight": _line_weight(dec(line["base_value"]), total, complete),
            }
            for line in position_lines
        ],
        key=lambda line: (-dec(line["base_value"]), line["instrument_id"]),
    )
    return {
        "account_id": state["account_id"],
        "as_of": state["as_of"],
        "base_currency": base_currency,
        "complete": complete,
        "total_value": canonical_decimal(total) if complete else None,
        "partial_value": canonical_decimal(total),
        "cash": cash_lines,
        "positions": position_lines,
        "allocation": allocation,
        "currency_exposure": [
            {"currency": currency, "base_value": canonical_decimal(value)}
            for currency, value in sorted(currency_values.items())
        ],
        "concentration": concentration,
        "gaps": [gap.as_dict() for gap in gaps],
    }


def aggregate_accounts(
    portfolio: Mapping[str, Any], account_values: list[Mapping[str, Any]]
) -> dict[str, Any]:
    complete = all(item["complete"] for item in account_values)
    partial_total = sum((dec(item["partial_value"]) for item in account_values), Decimal(0))
    allocation: dict[str, Decimal] = {}
    currency_exposure: dict[str, Decimal] = {}
    concentration: dict[str, dict[str, Any]] = {}
    positions = []
    cash = []
    gaps = []
    for account in account_values:
        account_id = account["account_id"]
        positions.extend({"account_id": account_id, **line} for line in account["positions"])
        cash.extend({"account_id": account_id, **line} for line in account["cash"])
        gaps.extend({"account_id": account_id, **gap} for gap in account["gaps"])
        for line in account["allocation"]:
            allocation[line["asset_type"]] = allocation.get(
                line["asset_type"], Decimal(0)
            ) + dec(line["base_value"])
        for line in account["currency_exposure"]:
            currency_exposure[line["currency"]] = currency_exposure.get(
                line["currency"], Decimal(0)
            ) + dec(line["base_value"])
        for line in account["concentration"]:
            current = concentration.setdefault(
                line["instrument_id"],
                {
                    "instrument_id": line["instrument_id"],
                    "identifier": line["identifier"],
                    "base_value": Decimal(0),
                },
            )
            current["base_value"] += dec(line["base_value"])
    denominator = partial_total if complete else Decimal(0)
    concentration_output = sorted(
        (
            {
                "instrument_id": line["instrument_id"],
                "identifier": line["identifier"],
                "base_value": canonical_decimal(line["base_value"]),
                "weight": _line_weight(line["base_value"], denominator, complete),
            }
            for line in concentration.values()
        ),
        key=lambda line: (-dec(line["base_value"]), line["instrument_id"]),
    )
    return {
        "portfolio_id": portfolio["id"],
        "name": portfolio["name"],
        "as_of": account_values[0]["as_of"] if account_values else None,
        "base_currency": portfolio["base_currency"],
        "complete": complete,
        "total_value": canonical_decimal(partial_total) if complete else None,
        "partial_value": canonical_decimal(partial_total),
        "accounts": list(account_values),
        "cash": cash,
        "positions": positions,
        "allocation": [
            {
                "asset_type": key,
                "base_value": canonical_decimal(value),
                "weight": _line_weight(value, denominator, complete),
            }
            for key, value in sorted(allocation.items())
            if value != 0
        ],
        "currency_exposure": [
            {"currency": key, "base_value": canonical_decimal(value)}
            for key, value in sorted(currency_exposure.items())
        ],
        "concentration": concentration_output,
        "gaps": gaps,
    }
