import asyncio

from src.auth.config import auth_settings
from src.users.models import User


async def _login(client, email="a@test.com", password="password123") -> dict:
    await client.post("/api/auth/signup", json={"email": email, "password": password})
    res = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    return res.json()


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
    body = res.json()
    assert body["accessToken"] and body["refreshToken"]
    assert body["user"]["email"] == "a@test.com"
    # the client is electron, not a browser: tokens come in the body, no cookies
    assert "set-cookie" not in res.headers


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
    old = (await _login(client))["refreshToken"]

    first = await client.post("/api/auth/refresh", json={"refreshToken": old})
    assert first.status_code == 200
    assert first.json()["accessToken"]
    assert first.json()["refreshToken"] != old

    # replay the old one
    again = await client.post("/api/auth/refresh", json={"refreshToken": old})
    assert again.status_code == 401
    assert again.json()["code"] == "invalid_refresh_token"


async def test_refresh_with_junk_token(client):
    res = await client.post("/api/auth/refresh", json={"refreshToken": "junk"})
    assert res.status_code == 401
    assert res.json()["code"] == "invalid_refresh_token"


async def test_two_refreshes_at_once_only_one_wins(client):
    token = (await _login(client))["refreshToken"]
    a, b = await asyncio.gather(
        client.post("/api/auth/refresh", json={"refreshToken": token}),
        client.post("/api/auth/refresh", json={"refreshToken": token}),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 401]


async def test_logout_revokes_and_is_idempotent(client):
    token = (await _login(client))["refreshToken"]
    assert (
        await client.post("/api/auth/logout", json={"refreshToken": token})
    ).status_code == 204
    assert (
        await client.post("/api/auth/logout", json={"refreshToken": token})
    ).status_code == 204
    # junk is fine too, logout never fails
    assert (
        await client.post("/api/auth/logout", json={"refreshToken": "junk"})
    ).status_code == 204

    assert (
        await client.post("/api/auth/refresh", json={"refreshToken": token})
    ).status_code == 401


async def test_me_requires_a_valid_token(client, user_headers):
    assert (await client.get("/api/users/me")).status_code == 401

    bad = await client.get("/api/users/me", headers={"Authorization": "Bearer junk"})
    assert bad.json()["code"] == "invalid_token"

    me = await client.get("/api/users/me", headers=user_headers)
    assert me.json()["email"] == "a@test.com"
    assert me.json()["minutesUsed"] == 0
    assert me.json()["minutesLimit"] == 60


# google / email-link users have no password, password login must just say "invalid"
async def test_password_login_on_account_without_password(client, db):
    db.add(User(email="g@test.com", firebase_uid="firebase-uid-1"))
    await db.commit()

    res = await client.post(
        "/api/auth/login", json={"email": "g@test.com", "password": "password123"}
    )
    assert res.status_code == 401
    assert res.json()["code"] == "invalid_credentials"


async def test_signup_closed_when_beta_is_full(client, monkeypatch):
    monkeypatch.setattr(auth_settings, "beta_signup_limit", 1)

    first = await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/auth/signup", json={"email": "b@test.com", "password": "password123"}
    )
    assert second.status_code == 403
    assert second.json()["code"] == "signup_closed"

    # people already in can still log in
    login = await client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "password123"}
    )
    assert login.status_code == 200
