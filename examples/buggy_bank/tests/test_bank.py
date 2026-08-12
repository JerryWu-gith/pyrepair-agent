import pytest
from bank import BankAccount


def test_deposit_increases_balance():
    account = BankAccount(100)

    account.deposit(20)

    assert account.balance == 120


def test_withdraw_reduces_balance():
    account = BankAccount(100)

    account.withdraw(30)

    assert account.balance == 70


def test_withdraw_rejects_insufficient_funds():
    account = BankAccount(20)

    with pytest.raises(ValueError, match="insufficient funds"):
        account.withdraw(30)
