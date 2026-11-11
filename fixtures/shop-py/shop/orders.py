"""Orders: create and cancel orders from a cart."""
from shop.auth import Authenticator
from shop.cart import Cart
from shop.payments import charge


class Order:
    """A placed order."""

    def __init__(self, username: str, total: float):
        self.username = username
        self.total = total
        self.status = "paid"


def create_order(auth: Authenticator, username: str, password: str, cart: Cart) -> dict:
    """Charge the cart total and record a paid order."""
    total = cart.total()
    payment = charge(auth, username, password, total)
    order = Order(username, payment["charged"])
    return {"username": order.username, "total": order.total, "status": order.status}


def cancel_order(order: dict) -> dict:
    """Cancel an order (demo: just flip the status)."""
    order["status"] = "cancelled"
    return order
