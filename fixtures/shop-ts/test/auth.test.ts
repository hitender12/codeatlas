// Tests for the src/auth module (fixture data for the indexer).
import assert from "assert";
import { Authenticator, hashPassword, verifyToken } from "../src/auth";

assert.strictEqual(hashPassword("abc"), hashPassword("abc"));
assert.strictEqual(verifyToken("x", "x"), true);
assert.strictEqual(verifyToken("x", "y"), false);

const auth = new Authenticator({ alice: hashPassword("hunter2") });
assert.strictEqual(auth.authenticate("alice", "hunter2"), true);
assert.strictEqual(auth.authenticate("alice", "wrong"), false);
assert.strictEqual(auth.login("alice", "hunter2")?.username, "alice");
assert.strictEqual(auth.login("alice", "wrong"), null);
