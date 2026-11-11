"""Tests for the billing module (fixture data for the indexer)."""
from billing import apply_discount, charge
from auth import Authenticator, hash_password


def test_apply_discount():
    assert apply_discount(100, 10) == 90


def test_charge_applies_discount_and_tax():
    auth = Authenticator({"alice": hash_password("hunter2")})
    result = charge(auth, "alice", "hunter2", 100)
    assert result["charged"] == round(90 * 1.20, 2)


def test_charge_rejects_bad_auth():
    auth = Authenticator({"alice": hash_password("hunter2")})
    try:
        charge(auth, "alice", "wrong", 100)
    except PermissionError:
        pass
    else:
        raise AssertionError("expected PermissionError")
