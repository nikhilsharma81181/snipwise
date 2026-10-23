import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import RefreshToken


async def add_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, token_hash: str, expires_at: datetime
) -> RefreshToken:
    row = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(row)
    await db.flush()
    return row


# only a token that is not revoked and not expired counts
async def get_active_refresh_token(
    db: AsyncSession, token_hash: str
) -> RefreshToken | None:
    return await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
    )


# guarded update: if two requests race with the same token, only one of them flips it.
# returns False for the loser
async def revoke_refresh_token(db: AsyncSession, token_id: uuid.UUID) -> bool:
    revoked_id = await db.scalar(
        update(RefreshToken)
        .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(RefreshToken.id)
    )
    return revoked_id is not None


async def revoke_by_hash(db: AsyncSession, token_hash: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
