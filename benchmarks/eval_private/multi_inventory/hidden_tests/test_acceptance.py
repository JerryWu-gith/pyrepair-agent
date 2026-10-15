import pytest
from warehouse import Warehouse
from reservations import Reservation

def test_contract():
    warehouse = Warehouse(20)
    first = Reservation(warehouse, 4)
    second = Reservation(warehouse, 2)
    assert warehouse.stock == 14
    first.cancel()
    first.cancel()
    assert warehouse.stock == 18
    second.cancel()
    assert warehouse.stock == 20

def test_preserved():
    warehouse = Warehouse(3)
    with pytest.raises(ValueError):
        Reservation(warehouse, 4)
    assert warehouse.stock == 3
