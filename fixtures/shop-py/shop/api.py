"""Public API surface for the shop."""
from shop.auth import Authenticator, hash_password
from shop.cart import Cart
from shop.catalog import get_product, list_products
from shop.orders import create_order

USERS = {"alice": hash_password("hunter2")}


def checkout(username: str, password: str, store: dict, items: list) -> dict:
    """Checkout: build a cart from items, then create an order."""
    auth = Authenticator(USERS)
    cart = Cart(store)
    for sku, qty in items:
        cart.add_item(sku, qty)
    return create_order(auth, username, password, cart)


def get_price(store: dict, sku: str) -> float:
    """Price lookup used by the storefront (no auth needed)."""
    product = get_product(store, sku)
    if product is None:
        raise KeyError(f"unknown sku: {sku}")
    return round(product["price"] * 1.20, 2)


def list_catalog(store: dict) -> list:
    """List the whole catalog for the storefront."""
    return list_products(store)
