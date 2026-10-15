# multi_orders

Prices and totals are integer cents. Quantities are nonnegative integers. subtotal sums price * quantity for every item. discount_percent returns 20 for vip, 10 for student and 0 otherwise. total applies the percentage with integer floor division. Empty items total zero.

Fix production code; preserve public APIs and visible tests.
