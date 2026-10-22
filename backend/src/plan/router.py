from typing import Annotated

from fastapi import APIRouter, Depends

from src.auth.dependencies import CurrentUser
from src.database import DbSession
from src.plan import service
from src.plan.dependencies import ai_rate_limit
from src.plan.llm import LLMClient, get_llm
from src.plan.schemas import PlanRequest, PlanResponse

router = APIRouter(prefix="/plan", tags=["plan"])


@router.post("", response_model=PlanResponse, dependencies=[Depends(ai_rate_limit)])
async def create_plan(
    body: PlanRequest,
    user: CurrentUser,
    db: DbSession,
    llm: Annotated[LLMClient, Depends(get_llm)],
):
    return await service.plan_for_user(db, user.id, llm, body.words, body.options)
