from service import total


def test_contract():
    assert total([(100, 3), (250, 2)], "vip") == 640
    assert total([(100, 2)], "regular") == 200
    assert total([(100, 0), (500, 2)], "student") == 900


def test_preserved():
    assert total([], "vip") == 0


def test_total_rounding():
    assert total([(1, 1), (1, 1)], "vip") == 1
    assert total([(101, 1), (101, 1)], "vip") == 161


def test_public_helpers():
    from discounts import discount_percent
    from pricing import subtotal

    assert subtotal([(100, 0), (5, 3)]) == 15
    assert discount_percent("vip") == 20
    assert discount_percent("student") == 10
    assert discount_percent("other") == 0
