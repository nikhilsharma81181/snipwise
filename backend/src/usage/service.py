import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.usage.models import UsageEvent


async def tokens_used_today(db: AsyncSession, user_id: uuid.UUID) -> int:
    # the day resets at midnight UTC for everyone
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await db.scalar(
        select(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens)).where(
            UsageEvent.user_id == user_id, UsageEvent.created_at >= midnight
        )
    )
    # SUM of no rows is NULL, not 0
    return total or 0


async def is_over_cap(db: AsyncSession, user_id: uuid.UUID) -> bool:
    return await tokens_used_today(db, user_id) >= settings.daily_token_cap
