"""Coordinate ledger operations and return transfer receipts."""


class TransferService:
    def __init__(self, ledger):
        self.ledger = ledger

    def transfer(self, request_id, source, destination, amount):
        self.ledger.debit(source, amount)
        self.ledger.credit(destination, amount)
        return (request_id, source, destination, amount)
