import pytest
from payments import charge, GatewayTimeout, PaymentUnavailable

def test_contract():
    def timeout():
        raise GatewayTimeout("slow")
    with pytest.raises(PaymentUnavailable):
        charge(timeout)
    assert charge(lambda: "receipt-99") == "receipt-99"
    def broken():
        raise ValueError("bad")
    with pytest.raises(ValueError, match="bad"):
        charge(broken)

def test_preserved():
    calls = []
    assert charge(lambda: calls.append(1) or "ok") == "ok"
    assert calls == [1]
