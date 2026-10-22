import json

from src.plan.llm import LLMReply

TEXT = "So um today we build uh today we will build an app"

# a valid POST /api/plan body for TEXT
PLAN_BODY = {
    "words": [
        {"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4}
        for i, t in enumerate(TEXT.split())
    ],
    "options": {"silences": True, "fillers": True, "bestTake": True, "zooms": True},
}

# what a well behaved model answers for TEXT
GOOD_ANSWER = json.dumps(
    {
        "drops": [
            {"startWord": 1, "endWord": 1, "reason": "filler"},
            {"startWord": 2, "endWord": 5, "reason": "retake"},
        ]
    }
)


# plays back scripted answers instead of calling a real AI, so tests are free and instant
class FakeLLM:
    def __init__(self, *answers: str | Exception):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> LLMReply:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMReply(text=answer, model="fake", input_tokens=100, output_tokens=20)
