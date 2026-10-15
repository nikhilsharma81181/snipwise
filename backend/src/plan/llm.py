from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMReply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    async def generate(self, prompt: str) -> LLMReply: ...


# the endpoint asks for this; tests swap it for FakeLLM with app.dependency_overrides
def get_llm() -> LLMClient:
    raise NotImplementedError("the Gemini client comes in a later step")
