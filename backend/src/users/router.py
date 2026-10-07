from fastapi import APIRouter

from src.auth.dependencies import CurrentUser
from src.config import settings
from src.database import DbSession
from src.users import service
from src.users.schemas import MeOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: DbSession):
    used = await service.minutes_used_this_month(db, user.id)
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,
        minutes_used=used,
        minutes_limit=settings.free_minutes_per_month,
    )
