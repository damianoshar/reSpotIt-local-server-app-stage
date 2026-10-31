"""services/user_auth_service.py — JWT user accounts (Phase 1).

Single-owner data is still global; this module only adds authentication
endpoints so clients can obtain a JWT. Per-user data scoping is a later phase.
"""

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlalchemy.orm import Session

from ..models import User

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_MINUTES = int(os.getenv("JWT_ACCESS_MINUTES", "30"))
REFRESH_TOKEN_DAYS = int(os.getenv("JWT_REFRESH_DAYS", "7"))

_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, digest = password_hash.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return hmac.compare_digest(calc, digest)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": _now() + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "iat": _now(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "refresh",
        "exp": _now() + timedelta(days=REFRESH_TOKEN_DAYS),
        "iat": _now(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise ValueError("wrong token type")
    return payload


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    try:
        uid = str(uuid.UUID(str(user_id)))
    except (ValueError, TypeError):
        uid = str(user_id)
    try:
        return db.query(User).filter(User.id == uid).first()
    except Exception:
        return None


def register_user(db: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        raise ValueError("email already registered")
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def issue_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(str(user.id), user.email),
        "refresh_token": create_refresh_token(str(user.id), user.email),
        "token_type": "bearer",
        # Keep the flat fields for Kotlin/older clients and add the nested
        # object the TypeScript remote layer expects (Elixir contract).
        "user_id": str(user.id),
        "email": user.email,
        "user": {"id": str(user.id), "email": user.email},
    }
