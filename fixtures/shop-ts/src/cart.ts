// Shopping cart: add/remove items and total them.
import { getProduct } from "./catalog";

export class Cart {
  constructor(private store: Record<string, unknown[]>, private items: Record<string, number> = {}) {}

  addItem(sku: string, qty: number = 1) {
    const product = getProduct(this.store, sku);
    if (!product) throw new Error(`unknown sku: ${sku}`);
    this.items[sku] = (this.items[sku] ?? 0) + qty;
  }

  removeItem(sku: string) {
    delete this.items[sku];
  }

  total() {
    let amount = 0;
    for (const sku of Object.keys(this.items)) {
      const product = getProduct(this.store, sku);
      amount += product.price * this.items[sku];
    }
    return Math.round(amount * 100) / 100;
  }
}
