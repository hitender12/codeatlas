"""Product catalog: list, look up, and search products."""
from dataclasses import dataclass

from shop.db import connect, query


@dataclass
class Product:
    """A sellable product."""

    sku: str
    name: str
    price: float
    stock: int = 0


def seed_store() -> dict:
    """Build a store with a few demo products."""
    store = connect()
    for product in [
        Product("SKU-1", "Safety helmet", 25.00, 40),
        Product("SKU-2", "Hi-vis vest", 12.50, 120),
        Product("SKU-3", "Steel-toe boots", 59.99, 15),
    ]:
        store["tables"]["products"].append(
            {"sku": product.sku, "name": product.name,
             "price": product.price, "stock": product.stock}
        )
    return store


def list_products(store: dict) -> list:
    """Return every product in the catalog."""
    return query(store, "products")


def get_product(store: dict, sku: str) -> dict | None:
    """Find one product by SKU, or None."""
    for product in query(store, "products"):
        if product["sku"] == sku:
            return product
    return None


def search_products(store: dict, needle: str) -> list:
    """Case-insensitive name search over the catalog."""
    needle = needle.lower()
    return [p for p in query(store, "products") if needle in p["name"].lower()]
