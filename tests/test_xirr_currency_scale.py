from decimal import Decimal, localcontext
import unittest

from clausula.analytics.performance import xirr


class XirrCurrencyScaleTests(unittest.TestCase):
    def assert_rate(self, expected: str, amounts: tuple[str, str], scale: str) -> None:
        with localcontext() as context:
            context.prec = 40
            flows = [("2023-01-01", Decimal(amounts[0]) * Decimal(scale)),
                     ("2024-01-01", Decimal(amounts[1]) * Decimal(scale))]
            actual = xirr(flows)
            self.assertIsNotNone(actual)
            assert actual is not None
            self.assertLess(abs(actual - Decimal(expected)), Decimal("1e-23"))

    def test_positive_return_is_currency_scale_invariant(self) -> None:
        for scale in ("1e-300", "1e-30", "1", "1e30", "1e300"):
            with self.subTest(scale=scale):
                self.assert_rate("0.1", ("-1", "1.1"), scale)

    def test_negative_return_is_currency_scale_invariant(self) -> None:
        for scale in ("1e-300", "1e-30", "1", "1e300"):
            with self.subTest(scale=scale):
                self.assert_rate("-0.2", ("-1", "0.8"), scale)

    def test_zero_return_is_currency_scale_invariant(self) -> None:
        for scale in ("1e-300", "1", "1e300"):
            with self.subTest(scale=scale):
                self.assert_rate("0", ("-1", "1"), scale)

    def test_sign_check_does_not_multiply_large_residuals(self) -> None:
        self.assert_rate("0.1", ("-1", "1.1"), "1e600000")

    def test_sign_check_does_not_underflow_tiny_residual_products(self) -> None:
        self.assert_rate("0.1", ("-1", "1.1"), "1e-600000")

    def test_same_day_nonzero_residual_has_no_bracket(self) -> None:
        self.assertIsNone(xirr([("2023-01-01", Decimal("-1")),
                                ("2023-01-01", Decimal("2"))]))

    def test_missing_signs_remain_undefined(self) -> None:
        for flows in ([], [("2023-01-01", Decimal(1))],
                      [("2023-01-01", Decimal(1)), ("2024-01-01", Decimal(2))]):
            self.assertIsNone(xirr(flows))

    def test_input_order_does_not_change_result(self) -> None:
        flows = [("2023-01-01", Decimal("-1e-30")), ("2024-01-01", Decimal("1.1e-30"))]
        self.assertEqual(xirr(flows), xirr(list(reversed(flows))))


if __name__ == "__main__":
    unittest.main()
