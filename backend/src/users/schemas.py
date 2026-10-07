import uuid

from src.schemas import CamelModel
from src.users.models import UserRole


class UserOut(CamelModel):
    id: uuid.UUID
    email: str
    role: UserRole


class MeOut(UserOut):
    minutes_used: float
    minutes_limit: int
