"""Authentication: passwords, tokens, and sessions for the shop."""
import hashlib
import hmac
import secrets
import time

SECRET = "demo-secret-change-me"
SESSION_TTL_SECONDS = 3600


def hash_password(password: str) -> str:
    """Hash a password with SHA-256 (demo only, not production auth)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_token(token: str, expected: str) -> bool:
    """Constant-time token comparison."""
    return hmac.compare_digest(token, expected)


def create_session(username: str) -> dict:
    """Create a signed session token for a user."""
    token = secrets.token_hex(16)
    return {
        "username": username,
        "token": token,
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }


class Authenticator:
    """Verifies user credentials against a user store."""

    def __init__(self, users: dict):
        self.users = users

    def authenticate(self, username: str, password: str) -> bool:
        """Return True when username/password match the stored hash."""
        stored = self.users.get(username)
        if stored is None:
            return False
        return verify_token(hash_password(password), stored)

    def login(self, username: str, password: str) -> dict | None:
        """Authenticate and, on success, return a fresh session."""
        if not self.authenticate(username, password):
            return None
        return create_session(username)

    def logout(self, session: dict) -> dict:
        """Invalidate a session (demo: just mark it expired)."""
        session["expires_at"] = 0
        return session
