from typing import Literal

from pydantic import Field

from src.schemas import CamelModel


class Word(CamelModel):
    text: str = Field(max_length=100)
    start: float = Field(ge=0)
    end: float = Field(ge=0)


# silences and zooms are handled on the Mac, the server only uses fillers and best_take
class PlanOptions(CamelModel):
    silences: bool = True
    fillers: bool = True
    best_take: bool = True
    zooms: bool = True


class PlanRequest(CamelModel):
    # a 60 min recording is roughly 9000 words, so 20k leaves plenty of room
    words: list[Word] = Field(min_length=1, max_length=20_000)
    options: PlanOptions


class Drop(CamelModel):
    start_word: int = Field(ge=0)
    end_word: int = Field(ge=0)
    reason: Literal["filler", "retake"]


class PlanResponse(CamelModel):
    drops: list[Drop]
    fallback_used: bool = False
    fallback_reason: str | None = None
