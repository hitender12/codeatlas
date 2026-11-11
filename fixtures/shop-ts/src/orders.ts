// Orders: create and cancel orders from a cart.
import { Authenticator } from "./auth";
import { Cart } from "./cart";
import { charge } from "./billing";

export function createOrder(auth: Authenticator, username: string, password: string, cart: Cart) {
  const total = cart.total();
  const payment = charge(auth, username, password, total);
  return { username, total: payment.charged, status: "paid" };
}

export function cancelOrder(order: { username: string; total: number; status: string }) {
  order.status = "cancelled";
  return order;
}
