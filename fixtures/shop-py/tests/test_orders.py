"""Tests for the shop.orders module (fixture data for the indexer)."""
from shop.auth import Authenticator, hash_password
from shop.cart import Cart
from shop.catalog import seed_store
from shop.orders import cancel_order, create_order


def _cart():
    store = seed_store()
    cart = Cart(store)
    cart.add_item("SKU-2", 2)
    return store, cart


def test_create_order_charges_cart_total():
    store, cart = _cart()
    auth = Authenticator({"alice": hash_password("hunter2")})
    order = create_order(auth, "alice", "hunter2", cart)
    assert order["status"] == "paid"
    assert order["total"] == 27.0  # 2 vests at 12.50, -10%, +20% tax


def test_cancel_order():
    store, cart = _cart()
    auth = Authenticator({"alice": hash_password("hunter2")})
    order = create_order(auth, "alice", "hunter2", cart)
    assert cancel_order(order)["status"] == "cancelled"
