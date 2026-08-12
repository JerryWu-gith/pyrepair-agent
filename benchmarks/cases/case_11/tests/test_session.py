from session import Session


def test_new_session_is_authenticated() -> None:
    assert Session("jerry").authenticated is True


def test_logout_clears_authentication_state() -> None:
    session = Session("jerry")
    session.logout()
    assert session.user is None
    assert session.authenticated is False
