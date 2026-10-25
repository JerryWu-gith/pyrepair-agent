import pytest
from ledger import Ledger
from service import TransferService


def test_missing_destination_does_not_debit_source():
    ledger = Ledger({"alice": 1000})
    service = TransferService(ledger)
    with pytest.raises(KeyError):
        service.transfer("missing", "alice", "bob", 250)
    assert ledger.balances == {"alice": 1000}


def test_ordinary_transfer_returns_receipt_and_moves_integer_cents():
    ledger = Ledger({"alice": 1000, "bob": 100})
    assert TransferService(ledger).transfer("normal", "alice", "bob", 250) == (
        "normal", "alice", "bob", 250
    )
    assert ledger.balances == {"alice": 750, "bob": 350}
