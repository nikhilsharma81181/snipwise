import json

import pytest

from src.config import settings
from src.main import app
from src.plan.llm import get_llm
from tests.conftest import make_user
from tests.fakes import FakeLLM

TEXT = "So um today we build uh today we will build an app"
BODY = {
    "words": [
        {"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4}
        for i, t in enumerate(TEXT.split())
    ],
    "options": {"silences": True, "fillers": True, "bestTake": True, "zooms": True},
}
GOOD = json.dumps(
    {
        "drops": [
            {"startWord": 1, "endWord": 1, "reason": "filler"},
            {"startWord": 2, "endWord": 5, "reason": "retake"},
        ]
    }
)


# swaps the real AI for a fake one for the length of a test
@pytest.fixture
def llm():
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


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
