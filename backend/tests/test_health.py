async def test_health_returns_ok(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


async def test_unknown_route_uses_error_shape(client):
    res = await client.get("/api/nope")
    assert res.status_code == 404
    assert res.json()["code"] == "not_found"
    assert set(res.json()) == {"code", "message"}


async def test_cors_allows_only_frontend_origin(client):
    preflight = {"Access-Control-Request-Method": "GET"}
    ok = await client.options("/api/health", headers={"Origin": "http://localhost:3000", **preflight})
    bad = await client.options("/api/health", headers={"Origin": "http://evil.test", **preflight})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
