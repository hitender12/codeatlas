"""Small formatting helpers."""


def format_price(amount: float, currency: str = "SGD") -> str:
    """Format an amount as e.g. 'SGD 12.50'."""
    return f"{currency} {amount:.2f}"


def slugify(text: str) -> str:
    """Lower-case slug: 'Hi-Vis Vest' -> 'hi-vis-vest'."""
    return text.lower().replace(" ", "-")
