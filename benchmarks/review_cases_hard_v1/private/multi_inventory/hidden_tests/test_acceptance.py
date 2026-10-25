import pytest
from reservations import Reservation
from warehouse import Warehouse


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


def test_exact_stock():
    warehouse = Warehouse(3)
    reservation = Reservation(warehouse, 3)
    assert warehouse.stock == 0
    reservation.cancel()
    reservation.cancel()
    assert warehouse.stock == 3


@pytest.mark.parametrize(
    "quantity", [0, -1, 1.5, "2"], ids=["zero", "negative", "fraction", "text"]
)
def test_invalid_quantity_preserves_state(quantity):
    warehouse = Warehouse(3)
    with pytest.raises(ValueError):
        Reservation(warehouse, quantity)
    assert warehouse.stock == 3
