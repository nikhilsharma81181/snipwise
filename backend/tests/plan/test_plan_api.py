from src.config import settings
from tests.conftest import make_user
from tests.fakes import GOOD_ANSWER as GOOD
from tests.fakes import PLAN_BODY as BODY


async def test_plan_needs_login(client, llm):
    res = await client.post("/api/plan", json=BODY)
    assert res.status_code == 401
    assert llm.prompts == []


async def test_plan_returns_drops(client, llm, user_headers):
    llm.answers = [GOOD]
    res = await client.post("/api/plan", json=BODY, headers=user_headers)

    assert res.status_code == 200
    assert res.json() == {
        "drops": [
            {"startWord": 1, "endWord": 1, "reason": "filler"},
            {"startWord": 2, "endWord": 5, "reason": "retake"},
        ],
        "fallbackUsed": False,
        "fallbackReason": None,
    }


async def test_plan_fallback_is_still_a_200(client, llm, user_headers):
    llm.answers = ["not json", "still not json"]
    res = await client.post("/api/plan", json=BODY, headers=user_headers)

    # the Mac still gets a usable plan (silences only) and shows a note
    assert res.status_code == 200
    assert res.json()["fallbackUsed"] is True
    assert res.json()["drops"] == []


async def test_plan_rejects_empty_transcript(client, llm, user_headers):
    res = await client.post(
        "/api/plan", json={**BODY, "words": []}, headers=user_headers
    )
    assert res.status_code == 422
    assert llm.prompts == []


async def test_plan_is_rate_limited_per_user(client, llm, monkeypatch):
    monkeypatch.setattr(settings, "ai_rate_limit_per_minute", 2)
    llm.answers = [GOOD, GOOD, GOOD]
    alice = await make_user(client, "alice@test.com")
    bob = await make_user(client, "bob@test.com")

    for _ in range(2):
        res = await client.post("/api/plan", json=BODY, headers=alice)
        assert res.status_code == 200

    res = await client.post("/api/plan", json=BODY, headers=alice)
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"

    # same IP, different user: bob has his own counter
    res = await client.post("/api/plan", json=BODY, headers=bob)
    assert res.status_code == 200
