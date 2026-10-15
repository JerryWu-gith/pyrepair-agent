class Reservation:
    def __init__(self, warehouse, quantity):
        warehouse.reserve(quantity)
        self.warehouse = warehouse
        self.quantity = quantity
        self.active = True

    def cancel(self):
        if self.active:
            self.warehouse.release(self.quantity)
