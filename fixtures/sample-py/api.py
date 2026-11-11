"""Public API surface for the sample shop."""
from billing import charge
from auth import Authenticator, hash_password

USERS = {"alice": "placeholder"}


def create_order(username: str, password: str, amount: float) -> dict:
    """Create an order: authenticate, then charge."""
    auth = Authenticator(USERS)
    return charge(auth, username, password, amount)


def get_price(amount: float) -> float:
    """Price lookup used by the storefront (no auth needed)."""
    return round(amount * 1.20, 2)
