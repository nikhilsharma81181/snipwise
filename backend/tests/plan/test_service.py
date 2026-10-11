import json

from src.plan.llm import LLMError
from src.plan.schemas import PlanOptions, Word
from src.plan.service import make_plan
from tests.fakes import FakeLLM

TEXT = "So um today we build uh today we will build an app"
WORDS = [
    Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate(TEXT.split())
]
ALL_ON = PlanOptions()


def _answer(*drops: tuple[int, int, str]) -> str:
    return json.dumps(
        {"drops": [{"startWord": s, "endWord": e, "reason": r} for s, e, r in drops]}
    )


GOOD = _answer((1, 1, "filler"), (2, 5, "retake"))


async def test_good_answer_is_returned():
    llm = FakeLLM(GOOD)
    plan = await make_plan(llm, WORDS, ALL_ON)

    assert [(d.start_word, d.end_word, d.reason) for d in plan.drops] == [
        (1, 1, "filler"),
        (2, 5, "retake"),
    ]
    assert plan.fallback_used is False
    assert len(llm.prompts) == 1


async def test_prompt_lists_words_with_their_index():
    llm = FakeLLM(GOOD)
    await make_plan(llm, WORDS, ALL_ON)

    assert "0 So" in llm.prompts[0]
    assert "11 app" in llm.prompts[0]


async def test_invalid_answer_is_retried_with_the_error():
    llm = FakeLLM(_answer((5, 12, "retake")), GOOD)
    plan = await make_plan(llm, WORDS, ALL_ON)

    assert len(plan.drops) == 2
    assert plan.fallback_used is False
    # the second prompt tells the model what was wrong
    assert "past the last word" in llm.prompts[1]


async def test_broken_json_is_retried():
    llm = FakeLLM("sure! here is your plan: {drops", GOOD)
    plan = await make_plan(llm, WORDS, ALL_ON)

    assert len(plan.drops) == 2
    assert len(llm.prompts) == 2


async def test_two_bad_answers_fall_back_to_silences_only():
    bad = _answer((0, 11, "retake"))  # drops everything
    llm = FakeLLM(bad, bad)
    plan = await make_plan(llm, WORDS, ALL_ON)

    assert plan.drops == []
    assert plan.fallback_used is True
    assert plan.fallback_reason == "ai_invalid"
    assert len(llm.prompts) == 2  # one retry, not more


async def test_ai_down_falls_back_without_retry():
    llm = FakeLLM(LLMError("timeout"))
    plan = await make_plan(llm, WORDS, ALL_ON)

    assert plan.drops == []
    assert plan.fallback_used is True
    assert plan.fallback_reason == "ai_unavailable"
    assert len(llm.prompts) == 1


async def test_no_ai_call_when_fillers_and_best_take_are_off():
    llm = FakeLLM()  # no answers: any call would crash the test
    plan = await make_plan(llm, WORDS, PlanOptions(fillers=False, best_take=False))

    assert plan.drops == []
    assert plan.fallback_used is False


async def test_drops_for_a_switched_off_option_are_discarded():
    # the model returned a filler even though fillers are off
    llm = FakeLLM(GOOD)
    plan = await make_plan(llm, WORDS, PlanOptions(fillers=False))

    assert [d.reason for d in plan.drops] == ["retake"]
