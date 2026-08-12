from grades import letter_grade


def test_score_above_ninety_is_a() -> None:
    assert letter_grade(95) == "A"


def test_score_of_ninety_is_a() -> None:
    assert letter_grade(90) == "A"
