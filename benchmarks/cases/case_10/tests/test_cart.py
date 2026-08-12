from cart import Cart


def test_new_cart_is_empty() -> None:
    assert Cart().item_count == 0


def test_add_updates_count_by_quantity() -> None:
    cart = Cart()
    cart.add(3)
    assert cart.item_count == 3
