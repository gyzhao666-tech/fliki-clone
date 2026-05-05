import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, Integer, ForeignKey, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    files: Mapped[List["File"]] = relationship("File", back_populates="folder", lazy="select")  # noqa: F821
    children: Mapped[List["Folder"]] = relationship("Folder", lazy="select")


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft|generating|done|error
    duration: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(20), default="video")  # video|audio
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    preview_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    script: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    template_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("voices.id", ondelete="SET NULL"), nullable=True)
    language: Mapped[str] = mapped_column(String(100), default="English")
    project_type: Mapped[str] = mapped_column(String(50), default="story_video")
    product_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_market: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    selling_points_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avoid_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="16:9")
    copyright_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="files")  # noqa: F821
    folder: Mapped[Optional["Folder"]] = relationship("Folder", back_populates="files")
    scenes: Mapped[List["Scene"]] = relationship("Scene", back_populates="file", cascade="all, delete-orphan", lazy="select")  # noqa: F821
    export_jobs: Mapped[List["ExportJob"]] = relationship("ExportJob", back_populates="file", cascade="all, delete-orphan", lazy="select")  # noqa: F821
