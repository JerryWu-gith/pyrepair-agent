from pagination import is_valid_page


def test_middle_page_is_valid() -> None:
    assert is_valid_page(2, 3) is True


def test_last_page_is_valid() -> None:
    assert is_valid_page(3, 3) is True
