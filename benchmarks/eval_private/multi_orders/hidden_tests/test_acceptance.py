from service import total

def test_contract():
    assert total([(100, 3), (250, 2)], "vip") == 640
    assert total([(100, 2)], "regular") == 200
    assert total([(100, 0), (500, 2)], "student") == 900

def test_preserved():
    assert total([], "vip") == 0
