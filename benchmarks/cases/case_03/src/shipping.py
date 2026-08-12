def shipping_fee(*, urgent: bool, weight_kg: float) -> int:
    if urgent and weight_kg > 10:
        return 15
    return 5
