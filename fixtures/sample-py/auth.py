"""Authentication helpers for the sample shop."""
import hashlib
import hmac

SECRET = "dev-only-secret"


def hash_password(password: str) -> str:
    """Hash a password with SHA-256 (demo only, not production auth)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_token(token: str, expected: str) -> bool:
    """Constant-time token comparison."""
    return hmac.compare_digest(token, expected)


class Authenticator:
    """Verifies user credentials."""

    def __init__(self, users: dict):
        self.users = users

    def authenticate(self, username: str, password: str) -> bool:
        stored = self.users.get(username)
        if stored is None:
            return False
        return verify_token(hash_password(password), stored)
