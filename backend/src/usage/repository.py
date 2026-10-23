import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.usage.models import UsageEvent, UsageKind


async def add_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: UsageKind,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> UsageEvent:
    event = UsageEvent(
        user_id=user_id,
        kind=kind,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(event)
    await db.flush()
    return event


async def sum_tokens_since(
    db: AsyncSession, user_id: uuid.UUID, since: datetime
) -> int:
    total = await db.scalar(
        select(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens)).where(
            UsageEvent.user_id == user_id, UsageEvent.created_at >= since
        )
    )
    # SUM of no rows is NULL, not 0
    return total or 0
