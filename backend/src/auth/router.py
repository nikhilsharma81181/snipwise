from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from src.auth import service
from src.auth.config import auth_settings
from src.auth.exceptions import InvalidRefreshToken
from src.auth.schemas import (
    AccessTokenResponse,
    LoginRequest,
    LoginResponse,
    SignupRequest,
)
from src.config import settings
from src.database import DbSession
from src.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/auth"  # browser only sends it to auth routes


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=auth_settings.refresh_token_expire_days * 24 * 60 * 60,
        path=COOKIE_PATH,
        httponly=True,  # js can't read it, so XSS can't steal it
        samesite="lax",
        secure=settings.environment == "production",
    )


@router.post("/signup", status_code=201, response_model=UserOut)
async def signup(body: SignupRequest, db: DbSession):
    return await service.signup(db, body.email, body.password)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DbSession, response: Response):
    user, access_token, refresh_token = await service.login(
        db, body.email, body.password
    )
    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(access_token=access_token, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    db: DbSession,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    if not refresh_token:
        raise InvalidRefreshToken()
    access_token, new_refresh_token = await service.refresh(db, refresh_token)
    _set_refresh_cookie(response, new_refresh_token)
    return AccessTokenResponse(access_token=access_token)


# always 204, so logout can never fail
@router.post("/logout", status_code=204)
async def logout(
    db: DbSession,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    await service.logout(db, refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
