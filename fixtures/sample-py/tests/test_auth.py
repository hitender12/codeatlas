"""Tests for the auth module (fixture data for the indexer)."""
from auth import Authenticator, hash_password, verify_token


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
