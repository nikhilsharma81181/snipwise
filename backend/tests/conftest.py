import os

import pytest
from dotenv import load_dotenv

# Load .env, then point the app at the test DB before src is imported,
# so tests can never touch the dev database
load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
# same for redis: db 15 is only for tests, dev uses db 0
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import src.auth.models
import src.users.models  # noqa: F401
from src.database import SessionLocal, engine
from src.main import app
from src.models import Base
from src.redis_client import redis_client

# belt and braces: refuse to run if we somehow ended up on the dev db
assert engine.url.database == "snipwise_test", (
    f"tests must use snipwise_test, got {engine.url.database}"
)
assert redis_client.connection_pool.connection_kwargs["db"] == 15, (
    "tests must use redis db 15"
)


@pytest.fixture
async def client():
    # Calls the app in memory, no real server or port needed
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# once per test run: fresh tables in snipwise_test
@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# after every test: wipe all rows so tests can't affect each other
@pytest.fixture(autouse=True)
async def clean_tables():
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    if names:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {names} CASCADE"))


# and wipe rate limit counters, so one test's requests don't count against the next
@pytest.fixture(autouse=True)
async def clean_redis():
    await redis_client.flushdb()
    yield


@pytest.fixture
async def db():
    async with SessionLocal() as session:
        yield session


async def make_user(
    client, email="a@test.com", password="password123"
) -> dict[str, str]:
    await client.post("/api/auth/signup", json={"email": email, "password": password})
    res = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    return {"Authorization": f"Bearer {res.json()['accessToken']}"}


@pytest.fixture
async def user_headers(client):
    return await make_user(client)


@pytest.fixture
async def other_headers(client):
    return await make_user(client, "b@test.com")
