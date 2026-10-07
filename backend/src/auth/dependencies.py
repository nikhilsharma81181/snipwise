import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.exceptions import AuthenticationRequired, InvalidAccessToken
from src.auth.utils import decode_access_token
from src.database import DbSession
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


CurrentUser = Annotated[User, Depends(get_current_user)]
