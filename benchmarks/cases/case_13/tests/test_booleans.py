from booleans import parse_bool


def test_true_text_becomes_true() -> None:
    assert parse_bool("true") is True


def test_false_text_becomes_false() -> None:
    assert parse_bool("false") is False
