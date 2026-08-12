from shipping import shipping_fee


def test_regular_shipping_uses_standard_fee() -> None:
    assert shipping_fee(urgent=False, weight_kg=2) == 5


def test_urgent_small_parcel_uses_express_fee() -> None:
    assert shipping_fee(urgent=True, weight_kg=2) == 15
