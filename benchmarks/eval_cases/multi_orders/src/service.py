from pricing import subtotal
from discounts import discount_percent


def total(items, tier):
    return subtotal(items) * (100 - discount_percent(tier)) // 100
