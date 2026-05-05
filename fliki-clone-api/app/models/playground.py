import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PlaygroundGen(Base):
    __tablename__ = "playground_gen"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(String(2048), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="z-turbo")
    ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="16:9")
    style: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
