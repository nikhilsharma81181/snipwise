from src.plan.llm import LLMReply


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
