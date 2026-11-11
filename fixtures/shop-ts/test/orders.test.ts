// Tests for the src/orders module (fixture data for the indexer).
import assert from "assert";
import { Authenticator, hashPassword } from "../src/auth";
import { Cart } from "../src/cart";
import { seedStore } from "../src/catalog";
import { cancelOrder, createOrder } from "../src/orders";

const store = seedStore();
const cart = new Cart(store);
cart.addItem("SKU-2", 2);

const auth = new Authenticator({ alice: hashPassword("hunter2") });
const order = createOrder(auth, "alice", "hunter2", cart);
assert.strictEqual(order.status, "paid");
assert.strictEqual(order.total, 27); // 2 vests at 12.50, -10%, +20% tax
assert.strictEqual(cancelOrder(order).status, "cancelled");
