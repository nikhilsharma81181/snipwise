import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.config import auth_settings
from src.auth.exceptions import AuthenticationRequired, InvalidAccessToken
from src.auth.utils import decode_access_token
from src.database import DbSession
from src.rate_limit import check_rate_limit
from src.users.models import User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None:
        raise AuthenticationRequired()

    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["userId"])
    except jwt.InvalidTokenError, KeyError, ValueError:
        raise InvalidAccessToken()

    user = await db.get(User, user_id)
    if user is None:
        raise InvalidAccessToken()
    return user


# per IP, because on signup/login we don't know who the user is yet
async def auth_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    await check_rate_limit(f"auth:{ip}", auth_settings.rate_limit_per_minute)


CurrentUser = Annotated[User, Depends(get_current_user)]
