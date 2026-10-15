from typing import Annotated

from fastapi import APIRouter, Depends

from src.plan import service
from src.plan.dependencies import ai_rate_limit
from src.plan.llm import LLMClient, get_llm
from src.plan.schemas import PlanRequest, PlanResponse

router = APIRouter(prefix="/plan", tags=["plan"])


# login is checked inside ai_rate_limit (it needs CurrentUser)
@router.post("", response_model=PlanResponse, dependencies=[Depends(ai_rate_limit)])
async def create_plan(body: PlanRequest, llm: Annotated[LLMClient, Depends(get_llm)]):
    return await service.make_plan(llm, body.words, body.options)
