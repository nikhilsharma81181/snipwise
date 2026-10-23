import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.users.models import User


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User)) or 0


async def add(db: AsyncSession, user: User) -> User:
    db.add(user)
    await db.flush()
    return user


async def delete(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.flush()
