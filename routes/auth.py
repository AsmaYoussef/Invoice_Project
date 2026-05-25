"""JWT authentication router and role-gating dependencies."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.db import get_db_connection

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET_KEY = os.getenv("JWT_SECRET", "diva-ocr-dev-secret-key-change-in-prod")
ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 60


# ---------------------------------------------------------------------------
# Password utilities (bcrypt directly -- passlib has compatibility issues
# with bcrypt>=4.1)
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


# ---------------------------------------------------------------------------
# JWT token utilities
# ---------------------------------------------------------------------------

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=DEFAULT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


# ---------------------------------------------------------------------------
# FastAPI dependencies for route protection
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> dict[str, Any]:
    """Extract and validate the Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = auth_header[7:]
    payload = decode_access_token(token)
    username = payload.get("sub")
    role = payload.get("role")
    if not username or not role:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    return {"sub": username, "role": role}


def require_role(required_role: str):
    """Return a dependency that enforces a specific role."""
    def _guard(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] != required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {required_role}.",
            )
        return user
    return _guard


# ---------------------------------------------------------------------------
# Login endpoint
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


@router.post("/login")
def login(body: LoginRequest):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT IDUser, Username, PasswordHash, Role, Status FROM system_users WHERE Username = %s",
            (body.username.strip(),),
        )
        user = cursor.fetchone()
    finally:
        conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if user.get("Status") != "ACTIVE":
        raise HTTPException(status_code=401, detail="Account is suspended. Contact your administrator.")

    if not verify_password(body.password, user["PasswordHash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    access_token = create_access_token(
        data={"sub": user["Username"], "role": user["Role"]},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["Role"],
        "username": user["Username"],
    }
