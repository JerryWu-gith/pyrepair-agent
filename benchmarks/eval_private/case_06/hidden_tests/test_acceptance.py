import pytest
from grades import letter_grade

def test_contract():
    assert letter_grade(90) == "A"
    assert letter_grade(89) == "B"
    assert letter_grade(0) == "B"

def test_preserved():
    assert letter_grade(100) == "A"
