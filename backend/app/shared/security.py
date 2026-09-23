import secrets
import time
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.shared.config import settings

_hasher = PasswordHasher()

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerificationError, InvalidHashError):
        return False


def _create_token(user_id: uuid.UUID, token_type: str, expires_seconds: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_seconds,
    }
    if token_type == REFRESH_TOKEN_TYPE:
        # jti делает каждую ротацию наблюдаемой (иначе два токена в одну секунду идентичны)
        payload["jti"] = secrets.token_hex(16)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, expires_minutes: int | None = None) -> str:
    minutes = (
        settings.access_token_expire_minutes if expires_minutes is None else expires_minutes
    )
    return _create_token(user_id, ACCESS_TOKEN_TYPE, minutes * 60)


def create_refresh_token(user_id: uuid.UUID, expires_days: int | None = None) -> str:
    days = settings.refresh_token_expire_days if expires_days is None else expires_days
    return _create_token(user_id, REFRESH_TOKEN_TYPE, days * 24 * 60 * 60)


def decode_token(token: str) -> dict[str, Any]:
    """Проверяет подпись и exp; бросает jwt.InvalidTokenError / ExpiredSignatureError."""
    decoded: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    return decoded
