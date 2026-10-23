from datetime import UTC, datetime, timedelta

from src.usage import repository
from src.usage.models import UsageKind
from src.users import repository as users_repository
from src.users.models import User

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


async def _user(db) -> User:
    return await users_repository.add(db, User(email="a@test.com"))


async def test_add_event_and_sum(db):
    user = await _user(db)
    await repository.add_event(db, user.id, UsageKind.PLAN, "m", 100, 20)
    await repository.add_event(db, user.id, UsageKind.CHAT, "m", 5, 5)

    assert await repository.sum_tokens_since(db, user.id, LONG_AGO) == 130


async def test_sum_ignores_rows_before_since(db):
    user = await _user(db)
    await repository.add_event(db, user.id, UsageKind.PLAN, "m", 100, 20)

    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert await repository.sum_tokens_since(db, user.id, tomorrow) == 0


async def test_repository_never_commits(db):
    user = await _user(db)
    await repository.add_event(db, user.id, UsageKind.PLAN, "m", 100, 20)
    await db.rollback()

    assert await repository.sum_tokens_since(db, user.id, LONG_AGO) == 0
