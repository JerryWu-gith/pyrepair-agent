import pytest
from payments import GatewayTimeout, PaymentUnavailable, charge


def test_successful_charge_returns_receipt() -> None:
    assert charge(lambda: "receipt-42") == "receipt-42"


def test_timeout_is_exposed_as_payment_unavailable() -> None:
    def timeout() -> str:
        raise GatewayTimeout("provider did not respond")

    with pytest.raises(PaymentUnavailable):
        charge(timeout)
