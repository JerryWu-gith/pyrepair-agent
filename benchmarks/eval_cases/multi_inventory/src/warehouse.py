class Warehouse:
    def __init__(self, stock):
        self.stock = stock

    def reserve(self, quantity):
        if quantity <= 0 or quantity > self.stock:
            raise ValueError('insufficient stock')
        self.stock -= 1

    def release(self, quantity):
        self.stock += quantity
