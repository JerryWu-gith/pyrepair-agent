class Cart:
    def __init__(self) -> None:
        self.item_count = 0

    def add(self, quantity: int) -> None:
        self.item_count += 1
