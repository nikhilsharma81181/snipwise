import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import repository
from src.auth.exceptions import (
    EMAIL_EXISTS,
    INVALID_CREDENTIALS,
    INVALID_REFRESH_TOKEN,
    SIGNUP_CLOSED,
)
from src.auth.utils import (
    auth_settings,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    password_hasher,
    verify_password,
)
from src.exceptions import AppError
from src.users import repository as users_repository
from src.users.models import User

# used when the email doesn't exist, so that path takes as long as a wrong password
_DUMMY_HASH = password_hasher.hash("not-a-real-password")


def _clean_email(email: str) -> str:
    return email.strip().lower()


async def _issue_refresh_token(db: AsyncSession, user: User) -> str:
    token, expires_at = create_refresh_token(user.id, user.role)
    await repository.add_refresh_token(db, user.id, hash_token(token), expires_at)
    return token


async def signup(db: AsyncSession, email: str, password: str) -> User:
    await _check_signup_open(db)
    user = User(email=_clean_email(email), password_hash=await hash_password(password))
    try:
        # flush sends the INSERT, so a duplicate email fails here
        await users_repository.add(db, user)
    except IntegrityError:
        # the unique constraint on email caught a duplicate
        await db.rollback()
        raise AppError(EMAIL_EXISTS)
    await db.commit()
    return user


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str, str]:
    user = await users_repository.get_by_email(db, _clean_email(email))
    if user is None or user.password_hash is None:
        await verify_password(password, _DUMMY_HASH)
        raise AppError(INVALID_CREDENTIALS)
    if not await verify_password(password, user.password_hash):
        raise AppError(INVALID_CREDENTIALS)

    access_token = create_access_token(user.id, user.role)
    refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return user, access_token, refresh_token


async def refresh(db: AsyncSession, raw_refresh_token: str) -> tuple[str, str]:
    try:
        decode_refresh_token(raw_refresh_token)
    except jwt.InvalidTokenError:
        raise AppError(INVALID_REFRESH_TOKEN)

    row = await repository.get_active_refresh_token(db, hash_token(raw_refresh_token))
    if row is None:
        raise AppError(INVALID_REFRESH_TOKEN)

    if not await repository.revoke_refresh_token(db, row.id):
        await db.rollback()
        raise AppError(INVALID_REFRESH_TOKEN)

    # role comes from the db, not the old token, so a role change applies on next refresh
    user = await users_repository.get_by_id(db, row.user_id)
    if user is None:
        await db.rollback()
        raise AppError(INVALID_REFRESH_TOKEN)
    access_token = create_access_token(user.id, user.role)
    new_refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return access_token, new_refresh_token


async def logout(db: AsyncSession, raw_refresh_token: str | None) -> None:
    if not raw_refresh_token:
        return
    await repository.revoke_by_hash(db, hash_token(raw_refresh_token))
    await db.commit()


async def _check_signup_open(db: AsyncSession) -> None:
    if await users_repository.count(db) >= auth_settings.beta_signup_limit:
        raise AppError(SIGNUP_CLOSED)
