"""Shopping cart: add/remove items and total them."""
from shop.catalog import get_product


class Cart:
    """A cart holds SKUs and quantities for one shopper."""

    def __init__(self, store: dict):
        self.store = store
        self.items: dict = {}

    def add_item(self, sku: str, qty: int = 1) -> None:
        """Add qty of a SKU; raises KeyError for an unknown SKU."""
        product = get_product(self.store, sku)
        if product is None:
            raise KeyError(f"unknown sku: {sku}")
        self.items[sku] = self.items.get(sku, 0) + qty

    def remove_item(self, sku: str) -> None:
        """Remove a SKU from the cart entirely."""
        self.items.pop(sku, None)

    def total(self) -> float:
        """Cart total at catalog prices."""
        amount = 0.0
        for sku, qty in self.items.items():
            product = get_product(self.store, sku)
            amount += product["price"] * qty
        return round(amount, 2)
