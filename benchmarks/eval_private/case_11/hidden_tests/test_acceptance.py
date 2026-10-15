import pytest
from session import Session

def test_contract():
    session = Session("alice")
    assert session.user == "alice"
    session.logout()
    assert session.user is None
    assert session.authenticated is False
    session.logout()
    assert session.authenticated is False

def test_preserved():
    assert Session("bob").user == "bob"
    assert Session("bob").authenticated is True
