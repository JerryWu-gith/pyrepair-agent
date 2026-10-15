from service import normalize

def test_order():
    assert normalize('2026-10-01T08:00:00+08:00') == '2026-10-01T00:00:00Z'
