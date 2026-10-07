
from fastapi import APIRouter

from src.auth import service
from src.auth.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    SignupRequest,
    TokenPair,
)
from src.database import DbSession
from src.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=201, response_model=UserOut)
async def signup(body: SignupRequest, db: DbSession):
    return await service.signup(db, body.email, body.password)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DbSession):
    user, access_token, refresh_token = await service.login(
        db, body.email, body.password
    )
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: DbSession):
    access_token, refresh_token = await service.refresh(db, body.refresh_token)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


# always 204, so logout can never fail
@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, db: DbSession):
    await service.logout(db, body.refresh_token)
