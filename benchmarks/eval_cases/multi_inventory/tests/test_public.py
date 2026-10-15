from warehouse import Warehouse
from reservations import Reservation

def test_order():
    warehouse = Warehouse(10)
    reservation = Reservation(warehouse, 3)
    assert warehouse.stock == 7
    reservation.cancel()
    reservation.cancel()
    assert warehouse.stock == 10
