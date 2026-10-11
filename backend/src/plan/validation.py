from src.plan.schemas import Drop, Word

MIN_KEPT_RATIO = 0.2


# the message goes back to the model on the retry, so it should say what to fix
class InvalidPlan(Exception):
    pass


def validate_drops(drops: list[Drop], words: list[Word]) -> None:
    last_end = -1
    for drop in sorted(drops, key=lambda d: d.start_word):
        if drop.end_word >= len(words):
            raise InvalidPlan(
                f"drop {drop.start_word}-{drop.end_word} is past the last word ({len(words) - 1})"
            )
        if drop.start_word > drop.end_word:
            raise InvalidPlan(
                f"drop {drop.start_word}-{drop.end_word} starts after it ends"
            )
        if drop.start_word <= last_end:
            raise InvalidPlan(
                f"drop {drop.start_word}-{drop.end_word} overlaps the previous drop"
            )
        last_end = drop.end_word

    # measured in seconds of speech, not word count
    total = sum(w.end - w.start for w in words)
    dropped = sum(
        words[i].end - words[i].start
        for d in drops
        for i in range(d.start_word, d.end_word + 1)
    )
    if total > 0 and (total - dropped) / total < MIN_KEPT_RATIO:
        raise InvalidPlan("plan keeps less than 20% of the speech, drop less")
