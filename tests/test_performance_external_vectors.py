from __future__ import annotations

from decimal import Decimal

from clausula.analytics import xirr


def test_xirr_matches_portfolio_performance_excel_verified_vector() -> None:
    """Cross-implementation golden vector, independent of Clausula fixtures.

    Portfolio Performance's IRRCalculationTest records the same dated cash flows
    as independently verified with Excel XIRR: buy -1000 on 2015-12-31, a 150
    gross dividend cash flow on 2016-06-01, and 1230 terminal sale proceeds on
    2016-12-31. Its expected annualized IRR is approximately 0.412128788 and the
    upstream regression uses a 1e-8 absolute tolerance for that rounded value.
    """

    rate = xirr(
        (
            ("2015-12-31", Decimal("-1000")),
            ("2016-06-01", Decimal("150")),
            ("2016-12-31", Decimal("1230")),
        )
    )

    assert rate is not None
    assert abs(rate - Decimal("0.412128788")) < Decimal("1e-8")
