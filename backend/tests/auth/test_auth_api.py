import asyncio

from tests.conftest import make_user


async def test_signup_then_login(client):
    res = await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    assert res.status_code == 201
    assert "password" not in res.text

    res = await client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "password123"}
    )
    assert res.status_code == 200
    assert res.json()["accessToken"]
    cookie = res.headers["set-cookie"]
    assert (
        "refresh_token=" in cookie
        and "HttpOnly" in cookie
        and "Path=/api/auth" in cookie
    )
    # refresh token only ever travels in the cookie, never in the body
    assert "refreshToken" not in res.json()


async def test_duplicate_email_ignores_case_and_spaces(client):
    await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    res = await client.post(
        "/api/auth/signup", json={"email": " A@Test.com ", "password": "password123"}
    )
    assert res.status_code == 409
    assert res.json()["code"] == "email_exists"


async def test_wrong_password_and_unknown_email_look_identical(client):
    await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    wrong = await client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "nope-nope"}
    )
    unknown = await client.post(
        "/api/auth/login", json={"email": "zz@test.com", "password": "nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_long_unicode_password_works(client):
    pw = "पासवर्ड-" + "x" * 90
    await client.post("/api/auth/signup", json={"email": "u@test.com", "password": pw})
    res = await client.post(
        "/api/auth/login", json={"email": "u@test.com", "password": pw}
    )
    assert res.status_code == 200


async def test_refresh_rotates_and_old_token_stops_working(client):
    await make_user(client)  # logs in, the client keeps the cookie
    old = client.cookies.get("refresh_token")

    first = await client.post("/api/auth/refresh")
    assert first.status_code == 200
    assert client.cookies.get("refresh_token") != old

    # replay the old one
    client.cookies.set("refresh_token", old, path="/api/auth")
    again = await client.post("/api/auth/refresh")
    assert again.status_code == 401
    assert again.json()["code"] == "invalid_refresh_token"


async def test_two_refreshes_at_once_only_one_wins(client):
    await make_user(client)
    a, b = await asyncio.gather(
        client.post("/api/auth/refresh"), client.post("/api/auth/refresh")
    )
    assert sorted([a.status_code, b.status_code]) == [200, 401]


async def test_logout_revokes_and_is_idempotent(client):
    await make_user(client)
    token = client.cookies.get("refresh_token")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/logout")).status_code == 204

    client.cookies.set("refresh_token", token, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_me_requires_a_valid_token(client, user_headers):
    assert (await client.get("/api/users/me")).status_code == 401

    bad = await client.get("/api/users/me", headers={"Authorization": "Bearer junk"})
    assert bad.json()["code"] == "invalid_token"

    me = await client.get("/api/users/me", headers=user_headers)
    assert me.json()["email"] == "a@test.com"
    assert me.json()["minutesUsed"] == 0
    assert me.json()["minutesLimit"] == 60
