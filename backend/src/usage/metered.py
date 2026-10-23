import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.plan.llm import LLMClient, LLMReply
from src.usage import repository
from src.usage.models import UsageKind


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
        # no commit here, the service commits once at the end of the request
        await repository.add_event(
            self.db,
            self.user_id,
            self.kind,
            reply.model,
            reply.input_tokens,
            reply.output_tokens,
        )
        return reply
