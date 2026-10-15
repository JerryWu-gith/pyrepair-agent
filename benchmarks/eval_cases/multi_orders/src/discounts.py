def discount_percent(tier):
    return {"vip": 5, "student": 10}.get(tier, 0)
