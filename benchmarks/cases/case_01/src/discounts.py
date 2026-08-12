def discount_rate(customer_tier: str) -> float:
    if customer_tier == "vip":
        return 0.20
    return 0.05
