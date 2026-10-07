import uuid

from sqlalchemy.ext.asyncio import AsyncSession


# TODO: sum project durations once projects exist (M1 Task 4)
async def minutes_used_this_month(db: AsyncSession, user_id: uuid.UUID) -> float:
    return 0.0
