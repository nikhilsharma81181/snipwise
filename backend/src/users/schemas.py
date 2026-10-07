import uuid

from src.schemas import CamelModel
from src.users.models import UserRole


class UserOut(CamelModel):
    id: uuid.UUID
    email: str
    role: UserRole