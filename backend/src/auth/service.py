import jwt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.exceptions import (
    EmailAlreadyExists,
    InvalidCredentials,
    InvalidRefreshToken,
)
from src.auth.models import RefreshToken
from src.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    password_hasher,
    verify_password,
)
from src.users.models import User

# used when the email doesn't exist, so that path takes as long as a wrong password
_DUMMY_HASH = password_hasher.hash("not-a-real-password")


def _clean_email(email: str) -> str:
    return email.strip().lower()


async def _issue_refresh_token(db: AsyncSession, user: User) -> str:
    token, expires_at = create_refresh_token(user.id, user.role)
    db.add(
        RefreshToken(
            user_id=user.id, token_hash=hash_token(token), expires_at=expires_at
        )
    )
    return token


async def signup(db: AsyncSession, email: str, password: str) -> User:
    user = User(email=_clean_email(email), password_hash=await hash_password(password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # the unique constraint on email caught a duplicate
        await db.rollback()
        raise EmailAlreadyExists()
    return user


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str, str]:
    user = await db.scalar(select(User).where(User.email == _clean_email(email)))
    if user is None or user.password_hash is None:
        await verify_password(password, _DUMMY_HASH)
        raise InvalidCredentials()
    if not await verify_password(password, user.password_hash):
        raise InvalidCredentials()

    access_token = create_access_token(user.id, user.role)
    refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return user, access_token, refresh_token


async def refresh(db: AsyncSession, raw_refresh_token: str) -> tuple[str, str]:
    try:
        decode_refresh_token(raw_refresh_token)
    except jwt.InvalidTokenError:
        raise InvalidRefreshToken()

    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw_refresh_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
    )
    if row is None:
        raise InvalidRefreshToken()

    # guarded update: if two requests race with the same token, only one of them flips it
    revoked_id = await db.scalar(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(RefreshToken.id)
    )
    if revoked_id is None:
        await db.rollback()
        raise InvalidRefreshToken()

    # role comes from the db, not the old token, so a role change applies on next refresh
    user = await db.get_one(User, row.user_id)
    access_token = create_access_token(user.id, user.role)
    new_refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return access_token, new_refresh_token


async def logout(db: AsyncSession, raw_refresh_token: str | None) -> None:
    if not raw_refresh_token:
        return
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_token(raw_refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
    await db.commit()
