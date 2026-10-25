"""Integer-cent account balances for an in-memory transfer service."""


class Ledger:
    def __init__(self, balances):
        self.balances = dict(balances)

    def debit(self, account, amount):
        if type(amount) is not int or amount <= 0:
            raise ValueError("amount must be positive integer cents")
        if account not in self.balances:
            raise KeyError(account)
        if self.balances[account] < amount:
            raise ValueError("insufficient funds")
        self.balances[account] -= amount

    def credit(self, account, amount):
        self.balances[account] += amount
