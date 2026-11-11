"""Billing: charge customers, applying a discount and tax."""
from auth import Authenticator, verify_token

TAX_RATE = 0.20


def apply_discount(amount: float, discount_pct: float) -> float:
    """Apply a percentage discount to an amount."""
    return amount * (1 - discount_pct / 100)


def charge(auth: Authenticator, username: str, password: str, amount: float) -> dict:
    """Charge a customer after authenticating them."""
    if not auth.authenticate(username, password):
        raise PermissionError("authentication failed")
    total = apply_discount(amount, 10) * (1 + TAX_RATE)
    return {"username": username, "charged": round(total, 2)}


def refund(username: str, amount: float) -> dict:
    """Refund a previous charge (no authentication in this demo)."""
    return {"username": username, "refunded": round(amount, 2)}
