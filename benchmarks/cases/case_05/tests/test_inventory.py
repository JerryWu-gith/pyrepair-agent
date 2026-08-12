from inventory import can_fulfill


def test_request_below_stock_can_be_fulfilled() -> None:
    assert can_fulfill(stock=5, requested=3) is True


def test_request_equal_to_stock_can_be_fulfilled() -> None:
    assert can_fulfill(stock=5, requested=5) is True
