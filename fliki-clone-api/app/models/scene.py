import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id: Mapped[str] = mapped_column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    script: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("voices.id", ondelete="SET NULL"), nullable=True)
    media_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # video|image|none
    character_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scene_goal: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    selling_point: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 视频生成相关字段
    video_prompt: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # LLM 转换的视觉化提示词
    video_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)  # 该分镜对应的视频片段 URL
    video_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="pending")  # pending|generating|done|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    file: Mapped["File"] = relationship("File", back_populates="scenes")  # noqa: F821
