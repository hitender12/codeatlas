"""Tiny in-memory database stand-in for the shop fixtures."""


def connect(path: str = ":memory:") -> dict:
    """Open a store (an in-memory dict of tables)."""
    return {"path": path, "tables": {"products": [], "orders": []}}


def query(store: dict, table: str) -> list:
    """Return every row in a table."""
    return list(store["tables"].get(table, []))


def save(store: dict, table: str, row: dict) -> None:
    """Append a row to a table."""
    store["tables"].setdefault(table, []).append(row)
