import pytest
from ledger import Ledger
from service import TransferService


def test_successful_request_replay_moves_funds_only_once():
    ledger = Ledger({"a": 1000, "b": 100})
    service = TransferService(ledger)
    receipt = service.transfer("replay", "a", "b", 200)
    assert service.transfer("replay", "a", "b", 200) == receipt
    assert ledger.balances == {"a": 800, "b": 300}


def test_replay_after_source_is_empty_returns_original_receipt():
    ledger = Ledger({"a": 75, "b": 10})
    service = TransferService(ledger)
    receipt = service.transfer("drain", "a", "b", 75)
    replay = None
    try:
        replay = service.transfer("drain", "a", "b", 75)
    except ValueError:
        pass
    assert replay == receipt
    assert ledger.balances == {"a": 0, "b": 85}


def test_conflicting_identifier_rejects_each_payload_change_unchanged():
    ledger = Ledger({"a": 1000, "b": 200, "c": 300})
    service = TransferService(ledger)
    service.transfer("used", "a", "b", 50)
    for payload in (("a", "b", 60), ("c", "b", 50), ("a", "c", 50)):
        rejected = False
        try:
            service.transfer("used", *payload)
        except ValueError:
            rejected = True
        assert rejected
        assert ledger.balances == {"a": 950, "b": 250, "c": 300}
    assert service.transfer("used", "a", "b", 50) == ("used", "a", "b", 50)
    assert ledger.balances == {"a": 950, "b": 250, "c": 300}


def test_missing_destination_failure_allows_same_identifier_retry():
    ledger = Ledger({"a": 900})
    service = TransferService(ledger)
    with pytest.raises(KeyError):
        service.transfer("retry-missing", "a", "b", 125)
    ledger.balances["b"] = 0
    assert service.transfer("retry-missing", "a", "b", 125) == (
        "retry-missing", "a", "b", 125
    )
    assert ledger.balances == {"a": 775, "b": 125}


def test_same_account_is_rejected_without_moving_funds():
    ledger = Ledger({"a": 1000})
    rejected = False
    try:
        TransferService(ledger).transfer("self", "a", "a", 100)
    except ValueError:
        rejected = True
    assert rejected
    assert ledger.balances == {"a": 1000}


def test_invalid_amounts_missing_source_and_insufficient_funds_are_preserved():
    ledger = Ledger({"a": 100, "b": 20})
    service = TransferService(ledger)
    for amount in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            service.transfer("invalid", "a", "b", amount)
        assert ledger.balances == {"a": 100, "b": 20}
    with pytest.raises(KeyError):
        service.transfer("source", "absent", "b", 10)
    with pytest.raises(ValueError):
        service.transfer("funds", "a", "b", 101)
    assert ledger.balances == {"a": 100, "b": 20}
    assert service.transfer("invalid", "a", "b", 25) == ("invalid", "a", "b", 25)
    assert ledger.balances == {"a": 75, "b": 45}


def test_failed_request_does_not_reserve_identifier_or_payload():
    ledger = Ledger({"a": 100, "b": 20})
    service = TransferService(ledger)
    with pytest.raises(ValueError):
        service.transfer("retry-funds", "a", "b", 101)
    assert service.transfer("retry-funds", "b", "a", 5) == ("retry-funds", "b", "a", 5)
    assert ledger.balances == {"a": 105, "b": 15}


def test_independent_identifiers_and_services_are_preserved():
    ledger = Ledger({"a": 100, "b": 20})
    service = TransferService(ledger)
    service.transfer("one", "a", "b", 10)
    service.transfer("two", "a", "b", 10)
    TransferService(ledger).transfer("one", "b", "a", 5)
    other = Ledger({"a": 100, "b": 20})
    TransferService(other).transfer("one", "b", "a", 5)
    assert ledger.balances == {"a": 85, "b": 35}
    assert other.balances == {"a": 105, "b": 15}
