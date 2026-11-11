// Tiny in-memory database stand-in for the shop fixtures.
export interface ProductRow {
  sku: string;
  name: string;
  price: number;
  stock: number;
}

export function connect(path: string): Record<string, unknown[]> {
  return { products: [], orders: [] };
}

export function query(store: Record<string, unknown[]>, table: string) {
  return store[table] ?? [];
}

export function save(store: Record<string, unknown[]>, table: string, row: unknown) {
  const rows = store[table] ?? [];
  rows.push(row);
  store[table] = rows;
}
