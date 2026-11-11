// Tests for the auth module (fixture data for the indexer).
const assert = require("assert");
const { Authenticator, hashPassword, verifyToken } = require("../auth");

assert.strictEqual(hashPassword("abc"), hashPassword("abc"));
assert.strictEqual(verifyToken("x", "x"), true);
assert.strictEqual(verifyToken("x", "y"), false);

const auth = new Authenticator({ alice: hashPassword("hunter2") });
assert.strictEqual(auth.authenticate("alice", "hunter2"), true);
assert.strictEqual(auth.authenticate("alice", "wrong"), false);
