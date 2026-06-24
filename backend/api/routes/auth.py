"""
Authentication endpoint: POST /api/login.

Validates one of the two fixed accounts (see api/auth.py) and returns a bearer
token plus the account's role. The frontend stores both and sends the token on
every subsequent request; require_admin then gates the state-changing routes.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.auth import authenticate

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Exchange username/password for a bearer token and role."""
    result = authenticate(body.username.strip(), body.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Kullanici adi veya parola hatali.")
    token, role = result
    return LoginResponse(token=token, role=role)
