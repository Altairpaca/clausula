from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, dec


class PerformanceError(ValueError):
    pass


def xirr(cash_flows: Sequence[tuple[str, Decimal]]) -> Decimal | None:
    if len(cash_flows) < 2:
        return None
    ordered = sorted((date.fromisoformat(day[:10]), dec(amount)) for day, amount in cash_flows)
    if not any(amount < 0 for _, amount in ordered) or not any(amount > 0 for _, amount in ordered):
        return None
    origin = ordered[0][0]

    def npv(rate: Decimal) -> Decimal:
        base = Decimal(1) + rate
        if base <= 0:
            raise PerformanceError("XIRR rate is outside the valid domain")
        with localcontext() as context:
            context.prec = 40
            return sum(
                (
                    amount
                    / (base ** (Decimal((day - origin).days) / Decimal(365)))
                    for day, amount in ordered
                ),
                Decimal(0),
            )

    low = Decimal("-0.999999999")
    high = Decimal(1)
    low_value = npv(low)
    high_value = npv(high)
    for _ in range(32):
        if low_value == 0:
            return low
        if high_value == 0:
            return high
        if low_value * high_value < 0:
            break
        high = high * 2 + 1
        high_value = npv(high)
    else:
        return None

    for _ in range(160):
        midpoint = (low + high) / 2
        value = npv(midpoint)
        if abs(value) < Decimal("1e-24") or high - low < Decimal("1e-24"):
            return midpoint
        if low_value * value <= 0:
            high = midpoint
            high_value = value
        else:
            low = midpoint
            low_value = value
    return (low + high) / 2


def performance_summary(points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        raise PerformanceError("performance requires at least two valuation points")
    ordered = sorted(points, key=lambda point: point["date"])
    if len({point["date"] for point in ordered}) != len(ordered):
        raise PerformanceError("performance dates must be unique")
    if any(point.get("complete") is not True for point in ordered):
        raise PerformanceError("performance requires complete valuations")

    linked = Decimal(1)
    peak = Decimal(1)
    maximum_drawdown = Decimal(0)
    series = []
    for index, point in enumerate(ordered):
        value = dec(point["value"])
        flow = dec(point.get("net_external_flow", "0"))
        if value < 0:
            raise PerformanceError("performance does not support negative portfolio value")
        period_return = None
        if index:
            previous = dec(ordered[index - 1]["value"])
            if previous == 0:
                if value - flow != 0:
                    raise PerformanceError("cannot compute return from zero opening value")
                period_return = Decimal(0)
            else:
                # Date-only external flows are conservatively treated as end-of-day.
                period_return = (value - flow) / previous - Decimal(1)
            linked *= Decimal(1) + period_return
        peak = max(peak, linked)
        drawdown = linked / peak - Decimal(1)
        maximum_drawdown = min(maximum_drawdown, drawdown)
        series.append(
            {
                "date": point["date"],
                "value": canonical_decimal(value),
                "net_external_flow": canonical_decimal(flow),
                "period_return": None
                if period_return is None
                else canonical_decimal(period_return),
                "drawdown": canonical_decimal(drawdown),
            }
        )

    opening = dec(ordered[0]["value"])
    mwr_flows = [(ordered[0]["date"], -opening)]
    mwr_flows.extend(
        (point["date"], -dec(point.get("net_external_flow", "0")))
        for point in ordered[1:]
        if dec(point.get("net_external_flow", "0")) != 0
    )
    mwr_flows.append((ordered[-1]["date"], dec(ordered[-1]["value"])))
    money_weighted = xirr(mwr_flows)
    return {
        "start_date": ordered[0]["date"],
        "end_date": ordered[-1]["date"],
        "time_weighted_return": canonical_decimal(linked - Decimal(1)),
        "money_weighted_return": None
        if money_weighted is None
        else canonical_decimal(money_weighted),
        "maximum_drawdown": canonical_decimal(maximum_drawdown),
        "external_flow_timing": "end_of_day",
        "series": series,
    }
