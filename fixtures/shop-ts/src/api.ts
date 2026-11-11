// Public API surface for the shop.
import { Authenticator, hashPassword } from "./auth";
import { getProduct, listProducts } from "./catalog";
import { createOrder } from "./orders";
import { Cart } from "./cart";

const USERS: Record<string, string> = { alice: hashPassword("hunter2") };

export function checkout(username: string, password: string, store: Record<string, unknown[]>, items: [string, number][]) {
  const auth = new Authenticator(USERS);
  const cart = new Cart(store);
  for (const [sku, qty] of items) {
    cart.addItem(sku, qty);
  }
  return createOrder(auth, username, password, cart);
}

export function getPrice(store: Record<string, unknown[]>, sku: string) {
  const product = getProduct(store, sku);
  if (!product) throw new Error(`unknown sku: ${sku}`);
  return Math.round(product.price * 1.2 * 100) / 100;
}

export function listCatalog(store: Record<string, unknown[]>) {
  return listProducts(store);
}
