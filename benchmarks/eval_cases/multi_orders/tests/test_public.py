from service import total

def test_order():
    assert total([(500, 2)], "vip") == 800
