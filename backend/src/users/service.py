import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.users import repository
from src.users.models import User


# TODO: sum project durations once projects exist (M1 Task 4)
async def minutes_used_this_month(db: AsyncSession, user_id: uuid.UUID) -> float:
    return 0.0


async def delete_user(db: AsyncSession, user: User) -> None:
    await repository.delete(db, user)
    await db.commit()
