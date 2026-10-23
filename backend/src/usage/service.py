import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.usage import repository


async def tokens_used_today(db: AsyncSession, user_id: uuid.UUID) -> int:
    # the day resets at midnight UTC for everyone
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return await repository.sum_tokens_since(db, user_id, midnight)


async def is_over_cap(db: AsyncSession, user_id: uuid.UUID) -> bool:
    return await tokens_used_today(db, user_id) >= settings.daily_token_cap
