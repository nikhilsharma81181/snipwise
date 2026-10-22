import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.plan.llm import LLMClient, LLMReply
from src.usage.models import UsageEvent, UsageKind


# wraps any LLM client and saves one usage row per call, retries included.
# the plan service doesn't know it's being metered, it just sees an LLMClient
class MeteredLLM:
    def __init__(
        self, llm: LLMClient, db: AsyncSession, user_id: uuid.UUID, kind: UsageKind
    ):
        self.llm = llm
        self.db = db
        self.user_id = user_id
        self.kind = kind

    async def generate(self, prompt: str) -> LLMReply:
        reply = await self.llm.generate(prompt)
        self.db.add(
            UsageEvent(
                user_id=self.user_id,
                kind=self.kind,
                model=reply.model,
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
            )
        )
        # commit right away, so the tokens count even if a later step fails
        await self.db.commit()
        return reply
