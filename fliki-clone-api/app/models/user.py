import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, Boolean, Integer, ARRAY, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    credits_total: Mapped[int] = mapped_column(Integer, default=5)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    youtube_channel_ids: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    referral_code: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True)
    # OAuth
    google_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    github_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    files: Mapped[List["File"]] = relationship("File", back_populates="user", lazy="select")  # noqa: F821
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="user", lazy="select")  # noqa: F821
