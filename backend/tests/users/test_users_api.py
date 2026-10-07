async def test_delete_account_needs_login(client):
    res = await client.delete("/api/users/me")
    assert res.status_code == 401


async def test_delete_account(client, user_headers):
    res = await client.delete("/api/users/me", headers=user_headers)
    assert res.status_code == 204

    # the access token is still signed, but the user behind it is gone
    me = await client.get("/api/users/me", headers=user_headers)
    assert me.status_code == 401

    # the email is free again
    res = await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    assert res.status_code == 201


async def test_delete_account_kills_refresh_tokens(client):
    await client.post(
        "/api/auth/signup", json={"email": "a@test.com", "password": "password123"}
    )
    login = (
        await client.post(
            "/api/auth/login", json={"email": "a@test.com", "password": "password123"}
        )
    ).json()
    headers = {"Authorization": f"Bearer {login['accessToken']}"}

    assert (await client.delete("/api/users/me", headers=headers)).status_code == 204

    res = await client.post(
        "/api/auth/refresh", json={"refreshToken": login["refreshToken"]}
    )
    assert res.status_code == 401
