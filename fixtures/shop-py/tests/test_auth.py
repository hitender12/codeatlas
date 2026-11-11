"""Tests for the shop.auth module (fixture data for the indexer)."""
from shop.auth import Authenticator, create_session, hash_password, verify_token


def test_hash_password_is_deterministic():
    assert hash_password("abc") == hash_password("abc")


def test_verify_token():
    assert verify_token("x", "x")
    assert not verify_token("x", "y")


def test_authenticate():
    auth = Authenticator({"alice": hash_password("hunter2")})
    assert auth.authenticate("alice", "hunter2")
    assert not auth.authenticate("alice", "wrong")
    assert not auth.authenticate("mallory", "hunter2")


def test_login_returns_session():
    auth = Authenticator({"alice": hash_password("hunter2")})
    session = auth.login("alice", "hunter2")
    assert session is not None
    assert session["username"] == "alice"
    assert create_session("bob")["username"] == "bob"
