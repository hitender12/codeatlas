"""Payments: charge and refund customers."""
from shop.auth import verify_token

TAX_RATE = 0.20


def apply_discount(amount: float, discount_pct: float) -> float:
    """Apply a percentage discount to an amount."""
    return amount * (1 - discount_pct / 100)


def charge(auth, username: str, password: str, amount: float) -> dict:
    """Charge a customer after authenticating them."""
    if not auth.authenticate(username, password):
        raise PermissionError("authentication failed")
    total = apply_discount(amount, 10) * (1 + TAX_RATE)
    return {"username": username, "charged": round(total, 2)}


def refund(username: str, amount: float) -> dict:
    """Refund a previous charge (no authentication in this demo)."""
    return {"username": username, "refunded": round(amount, 2)}


def verify_payment_token(token: str, expected: str) -> bool:
    """Check a payment token against the expected value."""
    return verify_token(token, expected)
