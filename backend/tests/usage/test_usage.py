from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from src.config import settings
from src.usage.models import UsageEvent, UsageKind
from src.usage.service import tokens_used_today
from src.users.models import User
from tests.fakes import GOOD_ANSWER, PLAN_BODY


async def _user_id(db, email="a@test.com"):
    return await db.scalar(select(User.id).where(User.email == email))


def _event(user_id, tokens_in, tokens_out, **extra) -> UsageEvent:
    return UsageEvent(
        user_id=user_id,
        kind=UsageKind.PLAN,
        model="test",
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        **extra,
    )


async def test_each_ai_call_is_recorded(client, db, llm, user_headers):
    llm.answers = [GOOD_ANSWER]
    await client.post("/api/plan", json=PLAN_BODY, headers=user_headers)

    rows = (await db.scalars(select(UsageEvent))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == await _user_id(db)
    assert (row.kind, row.model, row.input_tokens, row.output_tokens) == (
        UsageKind.PLAN,
        "fake",
        100,
        20,
    )


async def test_retries_are_recorded_too(client, db, llm, user_headers):
    # the bad first answer still cost tokens
    llm.answers = ["not json", GOOD_ANSWER]
    await client.post("/api/plan", json=PLAN_BODY, headers=user_headers)

    assert await db.scalar(select(func.count()).select_from(UsageEvent)) == 2


async def test_new_user_has_used_nothing(db, user_headers):
    assert await tokens_used_today(db, await _user_id(db)) == 0


async def test_tokens_used_today_counts_only_today_and_only_this_user(
    db, user_headers, other_headers
):
    me = await _user_id(db)
    someone_else = await _user_id(db, "b@test.com")
    yesterday = datetime.now(UTC) - timedelta(days=1)

    db.add_all(
        [
            _event(me, 100, 50),
            _event(me, 10, 5),
            _event(me, 9000, 9000, created_at=yesterday),
            _event(someone_else, 9000, 9000),
        ]
    )
    await db.commit()

    assert await tokens_used_today(db, me) == 165


async def test_over_the_cap_plan_falls_back_without_calling_ai(
    client, db, llm, user_headers, monkeypatch
):
    monkeypatch.setattr(settings, "daily_token_cap", 100)
    db.add(_event(await _user_id(db), 80, 40))
    await db.commit()

    res = await client.post("/api/plan", json=PLAN_BODY, headers=user_headers)

    assert res.status_code == 200
    assert res.json()["fallbackUsed"] is True
    assert res.json()["fallbackReason"] == "daily_cap"
    assert llm.prompts == []  # no tokens spent past the cap


async def test_usage_rows_go_with_a_deleted_account(client, db, llm, user_headers):
    llm.answers = [GOOD_ANSWER]
    await client.post("/api/plan", json=PLAN_BODY, headers=user_headers)
    await client.delete("/api/users/me", headers=user_headers)

    assert await db.scalar(select(func.count()).select_from(UsageEvent)) == 0
