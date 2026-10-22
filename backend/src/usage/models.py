import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


class UsageKind(StrEnum):
    PLAN = "plan"
    CHAT = "chat"


class UsageEvent(Base):
    __tablename__ = "usage_events"
    # the cap query is always "this user, since midnight", so one index on both columns
    __table_args__ = (
        Index("ix_usage_events_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[UsageKind] = mapped_column(
        Enum(UsageKind, native_enum=False, length=10)
    )
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
