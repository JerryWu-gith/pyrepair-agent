from money import dollars_to_cents


def test_whole_dollars_are_converted() -> None:
    assert dollars_to_cents("12") == 1200


def test_fractional_dollars_keep_cents() -> None:
    assert dollars_to_cents("12.50") == 1250
