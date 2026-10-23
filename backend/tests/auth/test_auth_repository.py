from datetime import UTC, datetime, timedelta

from src.auth import repository
from src.users import repository as users_repository
from src.users.models import User

IN_A_WEEK = datetime.now(UTC) + timedelta(days=7)
AN_HOUR_AGO = datetime.now(UTC) - timedelta(hours=1)


async def _user(db):
    return await users_repository.add(db, User(email="a@test.com"))


async def test_add_and_find_active_token(db):
    user = await _user(db)
    await repository.add_refresh_token(db, user.id, "h1", IN_A_WEEK)

    row = await repository.get_active_refresh_token(db, "h1")
    assert row is not None
    assert row.user_id == user.id


async def test_expired_token_is_not_active(db):
    user = await _user(db)
    await repository.add_refresh_token(db, user.id, "old", AN_HOUR_AGO)

    assert await repository.get_active_refresh_token(db, "old") is None


async def test_revoke_only_works_once(db):
    user = await _user(db)
    row = await repository.add_refresh_token(db, user.id, "h1", IN_A_WEEK)

    assert await repository.revoke_refresh_token(db, row.id) is True
    # the second caller loses the race
    assert await repository.revoke_refresh_token(db, row.id) is False
    assert await repository.get_active_refresh_token(db, "h1") is None


async def test_revoke_by_hash(db):
    user = await _user(db)
    await repository.add_refresh_token(db, user.id, "h1", IN_A_WEEK)

    await repository.revoke_by_hash(db, "h1")
    assert await repository.get_active_refresh_token(db, "h1") is None


async def test_repository_never_commits(db):
    user = await _user(db)
    await repository.add_refresh_token(db, user.id, "h1", IN_A_WEEK)
    await db.rollback()

    assert await repository.get_active_refresh_token(db, "h1") is None
