// Billing: charge customers, applying a discount and tax.
import { verifyToken } from "./auth";

export const TAX_RATE = 0.2;

export function applyDiscount(amount: number, discountPct: number): number {
  return amount * (1 - discountPct / 100);
}

export function charge(auth: { authenticate: (u: string, p: string) => boolean }, username: string, password: string, amount: number) {
  if (!auth.authenticate(username, password)) {
    throw new Error("authentication failed");
  }
  const total = applyDiscount(amount, 10) * (1 + TAX_RATE);
  return { username, charged: Math.round(total * 100) / 100 };
}

export function refund(username: string, amount: number) {
  return { username, refunded: Math.round(amount * 100) / 100 };
}

export function verifyPaymentToken(token: string, expected: string) {
  return verifyToken(token, expected);
}
