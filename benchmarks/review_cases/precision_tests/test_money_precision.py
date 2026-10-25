"""Review-only label validation; never installed in an Agent/Review input repo."""

from decimal import localcontext

import pytest
from money import dollars_to_cents


@pytest.mark.parametrize("precision", [2, 28, 64])
@pytest.mark.parametrize(
    "text, expected",
    [
        ("0", 0),
        ("12.50", 1250),
        ("0.29", 29),
        ("100.99", 10099),
        ("12345678901234567890123456789.01", 1234567890123456789012345678901),
        ("999999999999999999999999999999.99", 99999999999999999999999999999999),
    ],
)
def test_exact_cents_independent_of_decimal_context(text, expected, precision):
    with localcontext() as context:
        context.prec = precision
        assert dollars_to_cents(text) == expected
