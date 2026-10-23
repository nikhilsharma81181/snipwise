from src.users import repository
from src.users.models import User


async def test_add_and_find_by_email(db):
    user = await repository.add(db, User(email="a@test.com", password_hash="x"))

    # flush gave it an id without committing
    assert user.id is not None
    assert (await repository.get_by_email(db, "a@test.com")).id == user.id
    assert (await repository.get_by_id(db, user.id)).email == "a@test.com"


async def test_unknown_email_is_none(db):
    assert await repository.get_by_email(db, "nobody@test.com") is None


async def test_count(db):
    assert await repository.count(db) == 0
    await repository.add(db, User(email="a@test.com"))
    await repository.add(db, User(email="b@test.com"))
    assert await repository.count(db) == 2


async def test_repository_never_commits(db):
    # the service owns the transaction: a rollback must undo repository writes
    await repository.add(db, User(email="a@test.com"))
    await db.rollback()

    assert await repository.get_by_email(db, "a@test.com") is None
