"""生产元数据 7 张表（数据模型扩展 v1，2026-05-04）。

把原来塞在 `pipeline_steps.outputs_json` 里的「分镜 / 关键帧 / 视频片段 / 成片 / 质检 /
发布计划 / 指标 / 版本」拆成可 join、可查询、可 alembic 管控的表。

设计原则
-------
- 字段命名尽量与 Agent outputs_json 中已有键对齐，便于一一对应理解
- 跨 run 复用 / 版本切换的实体走 file_id 外键；run 级生命周期实体走 run_id
- 保留 `meta_json` 兜底，Agent 写到新表后不再依赖 outputs_json 的字段都丢这里
- 字符串 enum：与 pipeline.py 风格一致，不引入 PG ENUM 类型，alembic 维护成本低

7 张表
------
- `shot_lists`     一个 run 一个分镜表（含整段 script / topic / style_board / characters）
- `shots`          每个 shot 一行（含来自 ArtAgent 的 enhanced prompt + 来自 VideoAgent 的视频 URL）
- `renders`        EditAgent v4 每个 aspect 一行成片
- `reviews`        ReviewAgent 输出的每条 issue 一行
- `publish_plans`  发布计划（按平台 / 时间 / render）
- `metrics`        指标时间序列（cost / duration / view_count / ...）
- `versions`       同一 file_id 的 run 快照标签（便于切换/对比）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── shot_lists ───────────────────────────────────────────────────────────────


class ShotList(Base):
    """一个 run 一个分镜表（来自 ScriptAgent，被 ArtAgent 增强）。"""

    __tablename__ = "shot_lists"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # script 元信息
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    topic_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # art 增强
    style_board_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    character_cards_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    aspect_ratio: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── shots ────────────────────────────────────────────────────────────────────


class Shot(Base):
    """单个分镜：含 ArtAgent 关键帧 + VideoAgent 视频片段的执行结果。"""

    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    shot_list_id: Mapped[str] = mapped_column(
        String, ForeignKey("shot_lists.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    index: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    narration: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    camera: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # art 输出
    enhanced_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aspect_ratio: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    focus_character: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    keyframe_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keyframe_provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    keyframe_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    keyframe_size: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    keyframe_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # video 输出
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    video_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    video_mode: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        # "generate_video" / "image_to_video"
    )
    video_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    video_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_model_call_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    video_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── renders ──────────────────────────────────────────────────────────────────


RENDER_STATUSES = ("succeeded", "failed", "pending")


class Render(Base):
    """EditAgent 每出一个 aspect 的成片 = 一行 render。"""

    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    aspect_fit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    silent_video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subtitle_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narration_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    muxed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    burned_in_subtitles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    looped_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="succeeded")
    warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── reviews ──────────────────────────────────────────────────────────────────


REVIEW_SEVERITIES = ("error", "warning", "info")


class Review(Base):
    """ReviewAgent 输出的每条 issue 一行；便于按 severity / area 聚合统计。"""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    step_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_steps.id", ondelete="CASCADE"), nullable=True,
    )

    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    area: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── publish_plans ────────────────────────────────────────────────────────────


PUBLISH_STATUSES = ("draft", "scheduled", "published", "failed", "cancelled")


class PublishPlan(Base):
    """一次发布计划：把某个 render 推到某个平台，可定时。"""

    __tablename__ = "publish_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True,
    )
    render_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("renders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    platform: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 安全闸门：独立列（取代 v1 的 meta_json.confirm_real_publish）。
    # adapter 直接读这一列决定走 mock 路径还是真发路径；前端 PlanRow 暴露 toggle。
    confirm_real_publish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── metrics ──────────────────────────────────────────────────────────────────


class Metric(Base):
    """指标时间序列：cost_usd / duration_ms / shot_count / render_size_bytes / view_count / ...

    `kind` 是 string 不上 enum，避免每加一种就要 alembic；按需建组合索引。
    """

    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    step_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_steps.id", ondelete="CASCADE"), nullable=True,
    )
    file_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    value_num: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ── versions ─────────────────────────────────────────────────────────────────


class Version(Base):
    """一个 file_id 的 run 快照标签（v1 / v2 / final / ...），便于版本切换 + 发布关联。"""

    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    primary_render_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("renders.id", ondelete="SET NULL"), nullable=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "ShotList",
    "Shot",
    "Render",
    "Review",
    "PublishPlan",
    "Metric",
    "Version",
    "RENDER_STATUSES",
    "REVIEW_SEVERITIES",
    "PUBLISH_STATUSES",
]
