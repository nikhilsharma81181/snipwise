import logging

from pydantic import ValidationError

from src.plan.llm import LLMClient, LLMError
from src.plan.schemas import Drop, PlanOptions, PlanResponse, Word
from src.plan.validation import InvalidPlan, validate_drops
from src.schemas import CamelModel

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # the first try plus one retry with the error


# the JSON we ask the model for
class _ModelAnswer(CamelModel):
    drops: list[Drop]


async def make_plan(
    llm: LLMClient, words: list[Word], options: PlanOptions
) -> PlanResponse:
    # nothing for the AI to do, silences are cut on the Mac
    if not options.fillers and not options.best_take:
        return PlanResponse(drops=[])

    prompt = _build_prompt(words, options)
    error = None

    for _ in range(MAX_ATTEMPTS):
        if error:
            prompt += (
                f"\n\nYour last answer was rejected: {error}\nFix it and answer again."
            )
        try:
            reply = await llm.generate(prompt)
        except LLMError:
            logger.warning("plan: AI unavailable, falling back to silences only")
            return PlanResponse(
                drops=[], fallback_used=True, fallback_reason="ai_unavailable"
            )

        try:
            answer = _ModelAnswer.model_validate_json(reply.text)
            validate_drops(answer.drops, words)
        except (ValidationError, InvalidPlan) as e:
            error = str(e)
            continue

        return PlanResponse(drops=_only_enabled(answer.drops, options))

    # don't log the error itself, it can contain transcript text
    logger.warning("plan: %d invalid answers, falling back", MAX_ATTEMPTS)
    return PlanResponse(drops=[], fallback_used=True, fallback_reason="ai_invalid")


def _build_prompt(words: list[Word], options: PlanOptions) -> str:
    wanted = []
    if options.fillers:
        wanted.append('filler words like "um" and "uh" (reason "filler")')
    if options.best_take:
        wanted.append('repeated takes, keep only the last good one (reason "retake")')

    numbered = "\n".join(f"{i} {w.text}" for i, w in enumerate(words))
    return (
        "You edit talking-head videos. Below is the transcript, one word per line "
        "with its index.\n"
        f"Find: {'; '.join(wanted)}.\n"
        'Answer only with JSON: {"drops": [{"startWord": 0, "endWord": 0, '
        '"reason": "filler"}]}\n'
        "Ranges are inclusive. Keep at least 20% of the speech.\n\n"
        f"{numbered}"
    )


def _only_enabled(drops: list[Drop], options: PlanOptions) -> list[Drop]:
    allowed = set()
    if options.fillers:
        allowed.add("filler")
    if options.best_take:
        allowed.add("retake")
    return [d for d in drops if d.reason in allowed]
