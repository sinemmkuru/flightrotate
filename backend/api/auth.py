"""
Minimal role-based access control for FlightRotate (demo / thesis scope).

This is an ACCESS-CONTROL layer only — it decides *what a user may do*, not a
full identity system. Deliberately out of scope: audit/traceability ("who did
what"), password hashing, JWT/refresh tokens, a users table. Those would be the
next step for a real deployment; for the prototype two fixed users are enough.

Two fixed accounts:
  - admin  / admin123   -> role "admin"  : full access (behaves exactly as
                                            before this layer existed)
  - viewer / viewer123  -> role "viewer" : read-only (GET endpoints + the
                                            read-only /compare analysis)

How it works:
  - POST /api/login validates the credentials and hands back an opaque bearer
    token. Tokens live in an in-memory dict (token -> role); they are lost on
    restart, which is fine for a single-process prototype.
  - require_admin is a FastAPI dependency added to every state-changing
    endpoint. Admin passes through untouched; anyone else gets 403.
"""

import secrets
from typing import Optional

from fastapi import Header, HTTPException

# username -> (password, role). Plaintext on purpose: demo scope, see module docstring.
USERS = {
    "admin": ("admin123", "admin"),
    "viewer": ("viewer123", "viewer"),
}

# Issued bearer tokens: token -> role. In-memory, reset on server restart.
_TOKENS: dict[str, str] = {}


def authenticate(username: str, password: str) -> Optional[tuple[str, str]]:
    """Return (token, role) for valid credentials, else None."""
    record = USERS.get(username)
    if record is None or record[0] != password:
        return None
    password_ok, role = record
    token = secrets.token_hex(16)
    _TOKENS[token] = role
    return token, role


def role_for_token(token: Optional[str]) -> Optional[str]:
    """Look up the role a token was issued for (None if unknown/absent)."""
    if not token:
        return None
    return _TOKENS.get(token)


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extract the bearer token from an 'Authorization: Bearer <token>' header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def require_admin(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency: allow the request only for an admin token.

    Viewer tokens (and anonymous/invalid ones) are rejected with 403. Returns
    the role string so handlers *could* use it, though none need to today.
    """
    role = role_for_token(_token_from_header(authorization))
    if role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Bu islem icin admin yetkisi gerekir (viewer salt-okunur).",
        )
    return role
