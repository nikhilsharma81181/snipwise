import pytest
from pydantic import ValidationError

from src.plan.schemas import Drop, Word
from src.plan.validation import InvalidPlan, validate_drops


def _words(count: int, seconds: float = 1.0) -> list[Word]:
    return [
        Word(text=f"w{i}", start=i * seconds, end=(i + 1) * seconds)
        for i in range(count)
    ]


def _drop(start: int, end: int, reason: str = "filler") -> Drop:
    return Drop(start_word=start, end_word=end, reason=reason)  # pyright: ignore[reportArgumentType]


def test_good_plan_passes():
    validate_drops([_drop(1, 2), _drop(5, 5, "retake")], _words(10))


def test_no_drops_passes():
    validate_drops([], _words(10))


def test_drop_past_last_word():
    with pytest.raises(InvalidPlan, match="past the last word"):
        validate_drops([_drop(8, 10)], _words(10))


def test_drop_that_starts_after_it_ends():
    with pytest.raises(InvalidPlan, match="starts after it ends"):
        validate_drops([_drop(5, 3)], _words(10))


def test_overlapping_drops():
    with pytest.raises(InvalidPlan, match="overlaps"):
        validate_drops([_drop(2, 4), _drop(4, 6)], _words(10))


def test_out_of_order_and_touching_drops_are_fine():
    # the model may list drops in any order; 3-4 right after 0-2 is not an overlap
    validate_drops([_drop(3, 4), _drop(0, 2)], _words(10))


def test_overlap_found_even_when_out_of_order():
    with pytest.raises(InvalidPlan, match="overlaps"):
        validate_drops([_drop(5, 8), _drop(0, 6)], _words(10))


def test_keeping_exactly_20_percent_is_ok():
    validate_drops([_drop(0, 7)], _words(10))


def test_keeping_less_than_20_percent_fails():
    with pytest.raises(InvalidPlan, match="20%"):
        validate_drops([_drop(0, 8)], _words(10))


def test_20_percent_is_measured_by_time_not_word_count():
    # one long word (5 s) and nine short ones (0.1 s each)
    words = [Word(text="long", start=0, end=5)]
    words += [
        Word(text=f"w{i}", start=5 + i * 0.1, end=5.1 + i * 0.1) for i in range(9)
    ]

    # dropping 1 word of 10 keeps 90% of the words but only ~15% of the time
    with pytest.raises(InvalidPlan, match="20%"):
        validate_drops([_drop(0, 0)], words)


def test_drop_reads_camel_case_json():
    drop = Drop.model_validate({"startWord": 3, "endWord": 4, "reason": "retake"})
    assert (drop.start_word, drop.end_word) == (3, 4)


def test_drop_rejects_unknown_reason():
    # the model may only drop fillers and retakes; silences are cut on the Mac
    with pytest.raises(ValidationError):
        Drop.model_validate({"startWord": 3, "endWord": 4, "reason": "silence"})


def test_drop_rejects_negative_index():
    with pytest.raises(ValidationError):
        Drop.model_validate({"startWord": -1, "endWord": 4, "reason": "filler"})
