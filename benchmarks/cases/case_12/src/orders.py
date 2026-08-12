class Order:
    def __init__(self) -> None:
        self.status = "paid"
        self.history = ["paid"]

    def ship(self) -> None:
        self.status = "shipped"
