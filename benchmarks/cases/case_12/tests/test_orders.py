from orders import Order


def test_new_order_records_paid_state() -> None:
    assert Order().history == ["paid"]


def test_shipping_records_new_state() -> None:
    order = Order()
    order.ship()
    assert order.status == "shipped"
    assert order.history == ["paid", "shipped"]
