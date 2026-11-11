// Billing: charge customers, applying a discount and tax.
const { Authenticator } = require("./auth");

const TAX_RATE = 0.2;

function applyDiscount(amount, discountPct) {
  return amount * (1 - discountPct / 100);
}

function charge(auth, username, password, amount) {
  if (!auth.authenticate(username, password)) {
    throw new Error("authentication failed");
  }
  const total = applyDiscount(amount, 10) * (1 + TAX_RATE);
  return { username, charged: Math.round(total * 100) / 100 };
}

module.exports = { applyDiscount, charge, TAX_RATE };
