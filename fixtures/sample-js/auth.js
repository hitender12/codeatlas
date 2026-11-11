// Authentication helpers for the sample shop.
const crypto = require("crypto");

function hashPassword(password) {
  return crypto.createHash("sha256").update(password).digest("hex");
}

function verifyToken(token, expected) {
  return token === expected;
}

class Authenticator {
  constructor(users) {
    this.users = users;
  }

  authenticate(username, password) {
    const stored = this.users[username];
    if (!stored) return false;
    return verifyToken(hashPassword(password), stored);
  }
}

module.exports = { hashPassword, verifyToken, Authenticator };
