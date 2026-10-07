import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from src.auth.config import auth_settings

password_hasher = PasswordHash.recommended() 


# hashing is slow on purpose, so run it in a thread or it blocks every other request
async def hash_password(password: str) -> str:
    return await asyncio.to_thread(password_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(password_hasher.verify, password, password_hash)


def _create_token(user_id: uuid.UUID, role: str, secret: str, expires_at: datetime, **extra: Any) -> str:
    payload = {
        "userId": str(user_id),
        "role": role,
        "iat": datetime.now(UTC),
        "exp": expires_at,
        **extra,
    }
    return jwt.encode(payload, secret, algorithm=auth_settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=auth_settings.access_token_expire_minutes)
    return _create_token(user_id, role, auth_settings.jwt_secret.get_secret_value(), expires_at)


def create_refresh_token(user_id: uuid.UUID, role: str) -> tuple[str, datetime]:
    # no microseconds, so the expiry we save in the db matches the token's exp exactly
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=auth_settings.refresh_token_expire_days)
    secret = auth_settings.jwt_refresh_secret.get_secret_value()
    # jti makes two tokens issued in the same second still different
    token = _create_token(user_id, role, secret, expires_at, jti=str(uuid.uuid4()))
    return token, expires_at


# raises jwt.InvalidTokenError if fake, tampered or expired
def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, auth_settings.jwt_secret.get_secret_value(), algorithms=[auth_settings.jwt_algorithm])


def decode_refresh_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token, auth_settings.jwt_refresh_secret.get_secret_value(), algorithms=[auth_settings.jwt_algorithm]
    )


# we only store a hash of the refresh token, so a leaked db can't be used to log in
def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()