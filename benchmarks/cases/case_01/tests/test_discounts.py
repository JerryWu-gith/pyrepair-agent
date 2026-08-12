from discounts import discount_rate


def test_vip_discount() -> None:
    assert discount_rate("vip") == 0.20


def test_student_discount() -> None:
    assert discount_rate("student") == 0.10
