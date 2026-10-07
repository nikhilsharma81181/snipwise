from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from src.auth.config import auth_settings
from src.main import app
from src.redis_client import redis_client

WRONG_LOGIN = {"email": "nobody@test.com", "password": "wrongpass1"}


async def test_auth_routes_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(auth_settings, "rate_limit_per_minute", 3)

    # signup and login share one counter per IP
    await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    for _ in range(2):
        res = await client.post("/api/auth/login", json=WRONG_LOGIN)
        assert res.status_code == 401

    res = await client.post("/api/auth/login", json=WRONG_LOGIN)
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"


async def test_other_ip_has_its_own_limit(client, monkeypatch):
    monkeypatch.setattr(auth_settings, "rate_limit_per_minute", 1)
    await client.post("/api/auth/login", json=WRONG_LOGIN)
    res = await client.post("/api/auth/login", json=WRONG_LOGIN)
    assert res.status_code == 429

    other = ASGITransport(app=app, client=("10.0.0.2", 5000))
    async with AsyncClient(transport=other, base_url="http://test") as c:
        res = await c.post("/api/auth/login", json=WRONG_LOGIN)
    assert res.status_code == 401


async def test_counter_expires(client):
    await client.post("/api/auth/login", json=WRONG_LOGIN)

    # without a TTL the counter would live forever and block the IP for good
    keys = await redis_client.keys("rl:*")
    assert len(keys) == 1
    assert 0 < await redis_client.ttl(keys[0]) <= 60


async def test_other_routes_not_limited(client, monkeypatch):
    monkeypatch.setattr(auth_settings, "rate_limit_per_minute", 1)
    for _ in range(3):
        res = await client.get("/api/health")
        assert res.status_code == 200


async def test_fails_open_when_redis_is_down(client, monkeypatch):
    async def redis_down(*args, **kwargs):
        raise RedisConnectionError("redis is down")

    monkeypatch.setattr(redis_client, "incr", redis_down)

    # still a normal 401, not a 500 and not a 429
    res = await client.post("/api/auth/login", json=WRONG_LOGIN)
    assert res.status_code == 401
