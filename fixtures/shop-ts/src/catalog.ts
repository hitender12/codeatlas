// Product catalog: list, look up, and search products.
import { connect, query, save } from "./db";
import type { ProductRow } from "./db";

export interface Product {
  sku: string;
  name: string;
  price: number;
  stock: number;
}

export function seedStore(): Record<string, unknown[]> {
  const store = connect(":memory:");
  const products: ProductRow[] = [
    { sku: "SKU-1", name: "Safety helmet", price: 25.0, stock: 40 },
    { sku: "SKU-2", name: "Hi-vis vest", price: 12.5, stock: 120 },
    { sku: "SKU-3", name: "Steel-toe boots", price: 59.99, stock: 15 },
  ];
  for (const product of products) {
    save(store, "products", product);
  }
  return store;
}

export function listProducts(store: Record<string, unknown[]>) {
  return query(store, "products");
}

export function getProduct(store: Record<string, unknown[]>, sku: string) {
  const found = query(store, "products").filter((p) => p.sku === sku);
  return found.length > 0 ? found[0] : null;
}

export function searchProducts(store: Record<string, unknown[]>, needle: string) {
  const lower = needle.toLowerCase();
  return query(store, "products").filter((p) => p.name.toLowerCase().includes(lower));
}
